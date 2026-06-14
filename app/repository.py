import json
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.order_models import Acknowledgement, MessageAudit, MessageDirection, Order, OrderStatus, Shipment


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
    ) -> Shipment:
        shipment = Shipment(
            order_id=order_id,
            shipment_id=shipment_id,
            tracking_number=tracking_number,
            carrier=carrier,
            ship_date=ship_date,
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
    ) -> MessageAudit:
        payload_text = payload if isinstance(payload, str) else json.dumps(payload)
        audit = MessageAudit(
            message_id=message_id,
            message_type=message_type,
            direction=direction,
            payload=payload_text,
            status=status,
            correlation_id=correlation_id,
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

    def list_audit_messages(self, limit: int = 100) -> list[MessageAudit]:
        return (
            self.db.query(MessageAudit)
            .order_by(MessageAudit.timestamp.desc())
            .limit(limit)
            .all()
        )

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
            "ready_to_ship": 0,
            "shipped": 0,
        }
        for order in orders:
            key = order.status.value.lower()
            if key in stats:
                stats[key] += 1
        return stats

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
