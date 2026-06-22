import json
import logging
from datetime import datetime

from app.order_models import Order, OrderStatus, VerificationResult
from app.schemas_orders import (
    AcknowledgementResponse,
    EpcAllocationResponse,
    MessageAuditResponse,
    OrderDetailResponse,
    OrderSummaryResponse,
    RfidScanResponse,
    ShipmentResponse,
    WorkflowStepResponse,
)

logger = logging.getLogger(__name__)

WORKFLOW_STEPS = [
    (1, "Receive PO", OrderStatus.RECEIVED),
    (2, "PO Acknowledgement", OrderStatus.ACKNOWLEDGED),
    (3, "Product Preparation", OrderStatus.PICKING),
    (4, "EPC Allocation", OrderStatus.ALLOCATED),
    (5, "RFID Verification", OrderStatus.VERIFIED),
    (6, "ASN Sent", OrderStatus.ASN_SENT),
]

STATUS_ORDER = {
    OrderStatus.RECEIVED: 1,
    OrderStatus.ACKNOWLEDGED: 2,
    OrderStatus.PICKING: 3,
    OrderStatus.ALLOCATED: 4,
    OrderStatus.VERIFIED: 5,
    OrderStatus.ASN_SENT: 6,
}


def _line_item_count(order: Order) -> int:
    if order.po_lines:
        return len(order.po_lines)
    try:
        payload = json.loads(order.raw_po_json)
        return len(payload.get("payload", {}).get("line_items", []))
    except (json.JSONDecodeError, TypeError):
        return 0


def _gtin_count(order: Order) -> int:
    if order.po_lines:
        return len({line.gtin_14 for line in order.po_lines})
    return _line_item_count(order)


def _epc_count(order: Order) -> int:
    return len(order.epc_allocations) if order.epc_allocations else 0


def _verification_result(order: Order) -> str | None:
    if not order.rfid_scans:
        return None
    latest = max(order.rfid_scans, key=lambda scan: scan.created_at)
    if latest.result == VerificationResult.PENDING:
        return None
    return latest.result.value


def serialize_order_summary(order: Order) -> OrderSummaryResponse:
    return OrderSummaryResponse(
        id=order.id,
        po_number=order.po_number,
        buyer_id=order.buyer_id,
        seller_id=order.seller_id,
        correlation_message_id=order.correlation_message_id,
        received_timestamp=order.received_timestamp,
        status=order.status.value,
        line_item_count=_line_item_count(order),
        gtin_count=_gtin_count(order),
        epc_count=_epc_count(order),
        verification_result=_verification_result(order),
        asn_status="SENT" if order.shipment else "PENDING",
        has_acknowledgement=order.acknowledgement is not None,
        has_shipment=order.shipment is not None,
    )


def _step_timestamp(order: Order, step_status: OrderStatus) -> datetime | None:
    if step_status == OrderStatus.RECEIVED:
        return order.received_timestamp
    if step_status == OrderStatus.ACKNOWLEDGED and order.acknowledgement:
        return order.acknowledgement.timestamp
    if step_status == OrderStatus.ASN_SENT and order.shipment:
        return order.shipment.ship_date
    if step_status == OrderStatus.VERIFIED and order.rfid_scans:
        passed = [scan for scan in order.rfid_scans if scan.result == VerificationResult.PASS]
        if passed:
            return max(passed, key=lambda scan: scan.created_at).created_at
    return None


def build_workflow_steps(order: Order) -> list[WorkflowStepResponse]:
    current = STATUS_ORDER[order.status]
    steps = []
    for number, name, step_status in WORKFLOW_STEPS:
        completed = current >= STATUS_ORDER[step_status]
        step_state = "completed" if completed else "pending"
        if order.status == step_status:
            step_state = "active"
        steps.append(
            WorkflowStepResponse(
                step=number,
                name=name,
                status=step_state,
                completed=completed,
                timestamp=_step_timestamp(order, step_status),
                description=step_status.value,
            )
        )
    return steps


def _serialize_rfid_scan(scan) -> RfidScanResponse:
    def _load(value):
        if not value:
            return []
        return json.loads(value)

    return RfidScanResponse(
        id=scan.id,
        scan_session_id=scan.scan_session_id,
        expected_epcs=_load(scan.expected_epcs),
        scanned_epcs=_load(scan.scanned_epcs),
        matched_epcs=_load(scan.matched_epcs),
        missing_epcs=_load(scan.missing_epcs),
        unexpected_epcs=_load(scan.unexpected_epcs),
        result=scan.result.value,
        created_at=scan.created_at,
    )


def serialize_order_detail(order: Order) -> OrderDetailResponse:
    acknowledgement = None
    if order.acknowledgement:
        acknowledgement = AcknowledgementResponse(
            id=order.acknowledgement.id,
            message_id=order.acknowledgement.message_id,
            timestamp=order.acknowledgement.timestamp,
            raw_855_json=order.acknowledgement.raw_855_json,
        )

    shipment = None
    if order.shipment:
        shipment = ShipmentResponse(
            id=order.shipment.id,
            asn_number=order.shipment.asn_number,
            shipment_id=order.shipment.shipment_id,
            tracking_number=order.shipment.tracking_number,
            carrier=order.shipment.carrier,
            ship_date=order.shipment.ship_date,
            delivery_date=order.shipment.delivery_date,
            raw_856_json=order.shipment.raw_856_json,
        )

    allocations = [
        EpcAllocationResponse(
            id=item.id,
            gtin=item.gtin,
            epc=item.epc,
            po_line_id=item.po_line_id,
            allocated_at=item.allocated_at,
        )
        for item in (order.epc_allocations or [])
    ]

    latest_scan = None
    if order.rfid_scans:
        latest_scan = _serialize_rfid_scan(max(order.rfid_scans, key=lambda scan: scan.created_at))

    return OrderDetailResponse(
        id=order.id,
        po_number=order.po_number,
        buyer_id=order.buyer_id,
        seller_id=order.seller_id,
        correlation_message_id=order.correlation_message_id,
        received_timestamp=order.received_timestamp,
        status=order.status.value,
        raw_po_json=order.raw_po_json,
        acknowledgement=acknowledgement,
        shipment=shipment,
        epc_allocations=allocations,
        rfid_scan=latest_scan,
        workflow_steps=build_workflow_steps(order),
    )


def serialize_audit(entry) -> MessageAuditResponse:
    return MessageAuditResponse(
        id=entry.id,
        message_id=entry.message_id,
        message_type=entry.message_type,
        direction=entry.direction.value,
        timestamp=entry.timestamp,
        payload=entry.payload,
        status=entry.status,
        correlation_id=entry.correlation_id,
        topic=entry.topic,
    )
