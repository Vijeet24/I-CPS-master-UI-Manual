from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.edi.validators import EdiValidationError
from app.order_models import MessageDirection
from app.repository import OrderRepository
from app.schemas_orders import (
    MessageAuditResponse,
    OrderDetailResponse,
    OrderSummaryResponse,
    PurchaseOrderRequest,
)
from app.services.order_service import order_service
from app.services.workflow_ui import serialize_audit, serialize_order_detail, serialize_order_summary

router = APIRouter(tags=["purchase-orders"])


@router.post("/api/purchase-orders", response_model=OrderDetailResponse, status_code=status.HTTP_201_CREATED)
def receive_purchase_order(body: PurchaseOrderRequest, db: Session = Depends(get_db)):
    try:
        result = order_service.process_inbound_po(body.payload, source="API")
    except EdiValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    order = OrderRepository(db).get_order_by_id(result["order_id"])
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return serialize_order_detail(order)


@router.post("/api/po-ack")
def send_po_acknowledgement(order_id: int, db: Session = Depends(get_db)):
    repo = OrderRepository(db)
    order = repo.get_order_by_id(order_id)
    if order is None or order.acknowledgement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acknowledgement not found")

    audit_entries = repo.list_audit_for_order(order.correlation_message_id)
    ack_audit = next(
        (entry for entry in audit_entries if "855" in entry.message_type and entry.direction.value == "OUTBOUND"),
        None,
    )
    if ack_audit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ack audit entry not found")

    try:
        return order_service.send_audit_message(ack_audit.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/api/orders", response_model=list[OrderSummaryResponse])
def list_orders_alias(db: Session = Depends(get_db)):
    orders = OrderRepository(db).list_orders()
    return [serialize_order_summary(order) for order in orders]


@router.get("/api/mqtt/audit", response_model=list[MessageAuditResponse])
def mqtt_audit_log(
    limit: int = Query(100, ge=1, le=500),
    search: str | None = None,
    direction: str | None = None,
    db: Session = Depends(get_db),
):
    direction_enum = None
    if direction:
        try:
            direction_enum = MessageDirection(direction.upper())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid direction") from exc

    entries = OrderRepository(db).list_audit_messages(limit=limit, search=search, direction=direction_enum)
    return [serialize_audit(entry) for entry in entries]
