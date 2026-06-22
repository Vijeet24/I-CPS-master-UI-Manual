import json
import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.order_models import Order, OrderStatus, RfidScan, VerificationResult
from app.services.gtin_epc_resolver import gtin_epc_resolver, record_system_event
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)


class RfidServiceError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RfidService:
    def start_scan(self, db: Session, order_id: int, rescan: bool = False) -> RfidScan:
        order = (
            db.query(Order)
            .options(joinedload(Order.epc_allocations))
            .filter(Order.id == order_id)
            .first()
        )
        if order is None:
            raise RfidServiceError("Order not found")

        if order.status not in (OrderStatus.ALLOCATED, OrderStatus.VERIFIED):
            raise RfidServiceError(
                f"Order must be in ALLOCATED status to scan (current: {order.status.value})"
            )

        expected_epcs = gtin_epc_resolver.get_allocated_epcs(db, order_id)
        if not expected_epcs:
            raise RfidServiceError("No EPC allocations found for this order")

        if rescan:
            db.query(RfidScan).filter(
                RfidScan.order_id == order_id,
                RfidScan.result == VerificationResult.PENDING,
            ).update({"result": VerificationResult.FAIL})

        scan = RfidScan(
            order_id=order_id,
            scan_session_id=str(uuid.uuid4()),
            expected_epcs=json.dumps(expected_epcs),
            scanned_epcs=json.dumps([]),
            result=VerificationResult.PENDING,
        )
        db.add(scan)
        db.flush()

        simulated_reads = list(expected_epcs)
        scan.scanned_epcs = json.dumps(simulated_reads)
        db.flush()

        record_system_event(
            db,
            "RFID_SCAN_STARTED",
            order_id=order_id,
            correlation_id=order.correlation_message_id,
            payload={"scan_session_id": scan.scan_session_id, "rescan": rescan},
        )
        event_bus.publish(
            "rfid_scan_started",
            {"order_id": order_id, "scan_session_id": scan.scan_session_id},
        )
        logger.info("RFID scan started", extra={"order_id": order_id, "session": scan.scan_session_id})
        return scan

    def verify(self, db: Session, order_id: int, scan_session_id: str | None = None) -> RfidScan:
        order = db.query(Order).filter(Order.id == order_id).first()
        if order is None:
            raise RfidServiceError("Order not found")

        query = db.query(RfidScan).filter(RfidScan.order_id == order_id)
        if scan_session_id:
            query = query.filter(RfidScan.scan_session_id == scan_session_id)
        scan = query.order_by(RfidScan.created_at.desc()).first()
        if scan is None:
            raise RfidServiceError("No RFID scan session found. Start a scan first.")

        expected = set(json.loads(scan.expected_epcs))
        scanned = set(json.loads(scan.scanned_epcs or "[]"))
        matched = expected & scanned
        missing = expected - scanned
        unexpected = scanned - expected

        if missing or unexpected:
            result = VerificationResult.FAIL
            order.status = OrderStatus.ALLOCATED
        else:
            result = VerificationResult.PASS
            order.status = OrderStatus.VERIFIED

        scan.matched_epcs = json.dumps(sorted(matched))
        scan.missing_epcs = json.dumps(sorted(missing))
        scan.unexpected_epcs = json.dumps(sorted(unexpected))
        scan.result = result
        db.flush()

        record_system_event(
            db,
            "RFID_VERIFIED" if result == VerificationResult.PASS else "RFID_VERIFICATION_FAILED",
            order_id=order_id,
            correlation_id=order.correlation_message_id,
            payload={
                "scan_session_id": scan.scan_session_id,
                "result": result.value,
                "missing": sorted(missing),
                "unexpected": sorted(unexpected),
            },
        )
        event_bus.publish(
            "rfid_verified",
            {"order_id": order_id, "result": result.value, "scan_id": scan.id},
        )
        return scan

    def get_latest_result(self, db: Session, order_id: int) -> RfidScan | None:
        return (
            db.query(RfidScan)
            .filter(RfidScan.order_id == order_id)
            .order_by(RfidScan.created_at.desc())
            .first()
        )

    def set_scanned_epcs(self, db: Session, scan: RfidScan, scanned_epcs: list[str]) -> RfidScan:
        scan.scanned_epcs = json.dumps(scanned_epcs)
        db.flush()
        return scan


rfid_service = RfidService()
