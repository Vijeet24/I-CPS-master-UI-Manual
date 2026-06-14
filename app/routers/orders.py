import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.edi.validators import EdiValidationError
from app.mqtt.client import mqtt_service
from app.repository import OrderRepository
from app.schemas_orders import (
    MessageAuditResponse,
    MqttStatusResponse,
    OrderDetailResponse,
    OrderSummaryResponse,
    SendAuditMessageResponse,
    SimulatePurchaseOrderRequest,
    WorkflowStatsResponse,
)
from app.services.order_service import order_service
from app.services.workflow_ui import serialize_audit, serialize_order_detail, serialize_order_summary

router = APIRouter(prefix="/api/orders", tags=["orders"])

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


@router.get("/stats", response_model=WorkflowStatsResponse)
def get_workflow_stats(db: Session = Depends(get_db)):
    stats = OrderRepository(db).get_stats()
    return WorkflowStatsResponse(**stats)


@router.get("/mqtt-status", response_model=MqttStatusResponse)
def get_mqtt_status():
    return MqttStatusResponse(
        enabled=settings.mqtt_enabled,
        connected=mqtt_service.connected,
        broker=settings.mqtt_broker,
        port=settings.mqtt_port,
        subscribe_topic=settings.mqtt_subscribe_topic,
        ack_topic=settings.mqtt_ack_topic,
        asn_topic=settings.mqtt_asn_topic,
    )


@router.get("", response_model=list[OrderSummaryResponse])
def list_orders(db: Session = Depends(get_db)):
    orders = OrderRepository(db).list_orders()
    return [serialize_order_summary(order) for order in orders]


@router.get("/audit", response_model=list[MessageAuditResponse])
def list_message_audit(limit: int = 100, db: Session = Depends(get_db)):
    entries = OrderRepository(db).list_audit_messages(limit=limit)
    return [serialize_audit(entry) for entry in entries]


@router.post("/audit/{audit_id}/send", response_model=SendAuditMessageResponse)
def send_audit_message(audit_id: int):
    try:
        result = order_service.send_audit_message(audit_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return SendAuditMessageResponse(
        status=result["status"],
        audit_id=result["audit_id"],
        message_id=result["message_id"],
        topic=result.get("topic"),
    )


@router.get("/sample/purchase-order")
def get_sample_purchase_order():
    sample_path = SAMPLES_DIR / "inbound_850.json"
    if not sample_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample PO not found")
    return json.loads(sample_path.read_text(encoding="utf-8"))


@router.get("/{order_id}", response_model=OrderDetailResponse)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = OrderRepository(db).get_order_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return serialize_order_detail(order)


@router.get("/{order_id}/audit", response_model=list[MessageAuditResponse])
def get_order_audit(order_id: int, db: Session = Depends(get_db)):
    repo = OrderRepository(db)
    order = repo.get_order_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    entries = repo.list_audit_for_order(order.correlation_message_id)
    return [serialize_audit(entry) for entry in entries]


@router.post("/simulate", response_model=OrderDetailResponse, status_code=status.HTTP_201_CREATED)
def simulate_purchase_order(body: SimulatePurchaseOrderRequest, db: Session = Depends(get_db)):
    payload = dict(body.payload)
    if not payload.get("message_id"):
        import uuid

        payload["message_id"] = str(uuid.uuid4())

    try:
        result = order_service.process_inbound_po(payload, source="SIMULATION")
    except EdiValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc

    order = OrderRepository(db).get_order_by_id(result["order_id"])
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return serialize_order_detail(order)


@router.post("/{order_id}/ship")
def force_ship_order(order_id: int):
    try:
        return order_service.force_ship(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
