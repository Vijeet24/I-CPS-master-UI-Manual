import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.models import Product
from app.order_models import (
    Acknowledgement,
    EpcInventory,
    EpcStatus,
    MessageAudit,
    MessageDirection,
    Order,
    OrderStatus,
    Shipment,
)


class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_order_by_correlation(self, message_id: str) -> Order | None:
        return (
            self.db.query(Order)
            .filter(Order.correlation_message_id == message_id)
            .first()
        )

    def get_order_by_id(self, order_id: int) -> Order | None:
        return (
            self.db.query(Order)
            .options(
                joinedload(Order.acknowledgement),
                joinedload(Order.shipment),
                joinedload(Order.po_lines),
                joinedload(Order.epc_allocations),
                joinedload(Order.rfid_scans),
            )
            .filter(Order.id == order_id)
            .first()
        )

    def list_orders(self) -> list[Order]:
        return (
            self.db.query(Order)
            .options(
                joinedload(Order.acknowledgement),
                joinedload(Order.shipment),
                joinedload(Order.po_lines),
                joinedload(Order.epc_allocations),
            )
            .order_by(Order.received_timestamp.desc())
            .all()
        )

    def create_order(
        self,
        po_number: str,
        buyer_id: str,
        seller_id: str | None,
        correlation_message_id: str,
        raw_po_json: str,
    ) -> Order:
        order = Order(
            po_number=po_number,
            buyer_id=buyer_id,
            seller_id=seller_id,
            correlation_message_id=correlation_message_id,
            raw_po_json=raw_po_json,
            status=OrderStatus.RECEIVED,
        )
        self.db.add(order)
        self.db.flush()
        return order

    def update_order_status(self, order: Order, status: OrderStatus) -> Order:
        order.status = status
        self.db.flush()
        return order

    def create_acknowledgement(
        self, order_id: int, message_id: str, raw_855_json: str
    ) -> Acknowledgement:
        ack = Acknowledgement(
            order_id=order_id,
            message_id=message_id,
            raw_855_json=raw_855_json,
        )
        self.db.add(ack)
        self.db.flush()
        return ack

    def create_shipment(
        self,
        order_id: int,
        shipment_id: str,
        tracking_number: str,
        carrier: str,
        ship_date: datetime,
        raw_856_json: str,
        asn_number: str | None = None,
        delivery_date: datetime | None = None,
    ) -> Shipment:
        shipment = Shipment(
            order_id=order_id,
            asn_number=asn_number or shipment_id,
            shipment_id=shipment_id,
            tracking_number=tracking_number,
            carrier=carrier,
            ship_date=ship_date,
            delivery_date=delivery_date,
            raw_856_json=raw_856_json,
        )
        self.db.add(shipment)
        self.db.flush()
        return shipment

    def audit_message_exists(self, message_id: str, direction: MessageDirection) -> bool:
        return (
            self.db.query(MessageAudit)
            .filter(
                MessageAudit.message_id == message_id,
                MessageAudit.direction == direction,
            )
            .first()
            is not None
        )

    def record_audit(
        self,
        message_id: str,
        message_type: str,
        direction: MessageDirection,
        payload: dict | str,
        status: str = "PROCESSED",
        correlation_id: str | None = None,
        topic: str | None = None,
    ) -> MessageAudit:
        payload_text = payload if isinstance(payload, str) else json.dumps(payload)
        audit = MessageAudit(
            message_id=message_id,
            message_type=message_type,
            direction=direction,
            payload=payload_text,
            status=status,
            correlation_id=correlation_id,
            topic=topic,
        )
        self.db.add(audit)
        self.db.flush()
        return audit

    def get_audit_by_id(self, audit_id: int) -> MessageAudit | None:
        return self.db.query(MessageAudit).filter(MessageAudit.id == audit_id).first()

    def update_audit_status(self, audit: MessageAudit, status: str) -> MessageAudit:
        audit.status = status
        self.db.flush()
        return audit

    def list_audit_messages(
        self,
        limit: int = 100,
        search: str | None = None,
        direction: MessageDirection | None = None,
    ) -> list[MessageAudit]:
        query = self.db.query(MessageAudit)
        if direction:
            query = query.filter(MessageAudit.direction == direction)
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                (MessageAudit.message_type.ilike(pattern))
                | (MessageAudit.correlation_id.ilike(pattern))
                | (MessageAudit.message_id.ilike(pattern))
                | (MessageAudit.topic.ilike(pattern))
            )
        return query.order_by(MessageAudit.timestamp.desc()).limit(limit).all()

    def list_audit_for_order(self, correlation_id: str) -> list[MessageAudit]:
        return (
            self.db.query(MessageAudit)
            .filter(MessageAudit.correlation_id == correlation_id)
            .order_by(MessageAudit.timestamp.asc())
            .all()
        )

    def get_stats(self) -> dict[str, int]:
        orders = self.db.query(Order).all()
        stats = {
            "total": len(orders),
            "received": 0,
            "acknowledged": 0,
            "picking": 0,
            "allocated": 0,
            "verified": 0,
            "asn_sent": 0,
            "verification_failures": 0,
        }
        for order in orders:
            key = order.status.value.lower()
            if key in stats:
                stats[key] += 1
        return stats

    def get_dashboard_metrics(self) -> dict:
        stats = self.get_stats()
        total_products = self.db.query(Product).count()
        total_epcs_available = (
            self.db.query(EpcInventory)
            .filter(EpcInventory.status == EpcStatus.AVAILABLE)
            .count()
        )
        stats["verification_failures"] = self.count_verification_failures()
        return {
            **stats,
            "purchase_orders_received": stats["received"] + stats["acknowledged"] + stats["picking"] + stats["allocated"] + stats["verified"] + stats["asn_sent"],
            "po_acknowledgements_sent": self.db.query(Acknowledgement).count(),
            "orders_in_preparation": stats["picking"] + stats["allocated"],
            "rfid_verification_failures": stats["verification_failures"],
            "asn_sent": stats["asn_sent"],
            "total_products": total_products,
            "total_epcs_available": total_epcs_available,
            "pipeline": {
                "RECEIVED": stats["received"],
                "ACKNOWLEDGED": stats["acknowledged"],
                "PICKING": stats["picking"],
                "ALLOCATED": stats["allocated"],
                "VERIFIED": stats["verified"],
                "ASN_SENT": stats["asn_sent"],
            },
        }

    def count_verification_failures(self) -> int:
        from app.order_models import RfidScan, VerificationResult

        return (
            self.db.query(RfidScan)
            .filter(RfidScan.result == VerificationResult.FAIL)
            .count()
        )

    def list_asn_tracking(self, limit: int = 50) -> list[Shipment]:
        return (
            self.db.query(Shipment)
            .options(joinedload(Shipment.order).joinedload(Order.epc_allocations))
            .order_by(Shipment.ship_date.desc())
            .limit(limit)
            .all()
        )

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
