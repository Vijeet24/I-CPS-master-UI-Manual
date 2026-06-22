import json
import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.order_models import EpcAllocation, EpcInventory, EpcStatus, Order, OrderStatus, PoLine, SystemEvent
from app.models import Product

logger = logging.getLogger(__name__)


class GtinEpcResolverError(Exception):
    def __init__(self, message: str, gtin: str | None = None):
        super().__init__(message)
        self.message = message
        self.gtin = gtin


class GtinEpcResolver:
    def allocate_for_order(self, db: Session, order: Order) -> list[EpcAllocation]:
        allocations: list[EpcAllocation] = []
        for line in order.po_lines:
            line_allocations = self.allocate(db, line.gtin_14, line.quantity_ordered, order.id, line.id)
            allocations.extend(line_allocations)
        return allocations

    def allocate(
        self,
        db: Session,
        gtin: str,
        quantity: int,
        order_id: int,
        po_line_id: int,
    ) -> list[EpcAllocation]:
        if quantity <= 0:
            raise GtinEpcResolverError("Quantity must be positive", gtin)

        product = db.query(Product).filter(Product.gtin_14 == gtin).first()
        if product is None:
            raise GtinEpcResolverError(f"No product catalog entry for GTIN {gtin}", gtin)

        available = (
            db.query(EpcInventory)
            .filter(EpcInventory.gtin == gtin, EpcInventory.status == EpcStatus.AVAILABLE)
            .order_by(EpcInventory.id)
            .limit(quantity)
            .all()
        )
        if len(available) < quantity:
            raise GtinEpcResolverError(
                f"Insufficient EPC inventory for GTIN {gtin}: need {quantity}, have {len(available)}",
                gtin,
            )

        allocations: list[EpcAllocation] = []
        now = datetime.utcnow()
        for item in available:
            item.status = EpcStatus.ALLOCATED
            item.last_updated = now
            allocation = EpcAllocation(
                order_id=order_id,
                po_line_id=po_line_id,
                epc=item.epc,
                gtin=gtin,
                allocated_at=now,
            )
            db.add(allocation)
            allocations.append(allocation)

        db.flush()
        logger.info(
            "EPCs allocated",
            extra={"gtin": gtin, "quantity": quantity, "order_id": order_id, "epcs": [a.epc for a in allocations]},
        )
        return allocations

    def get_allocated_epcs(self, db: Session, order_id: int) -> list[str]:
        rows = db.query(EpcAllocation).filter(EpcAllocation.order_id == order_id).all()
        return [row.epc for row in rows]

    def release_allocations(self, db: Session, order_id: int) -> None:
        allocations = db.query(EpcAllocation).filter(EpcAllocation.order_id == order_id).all()
        for allocation in allocations:
            inventory = db.query(EpcInventory).filter(EpcInventory.epc == allocation.epc).first()
            if inventory and inventory.status == EpcStatus.ALLOCATED:
                inventory.status = EpcStatus.AVAILABLE
                inventory.last_updated = datetime.utcnow()
            db.delete(allocation)
        db.flush()

    def mark_shipped(self, db: Session, order_id: int) -> None:
        allocations = db.query(EpcAllocation).filter(EpcAllocation.order_id == order_id).all()
        now = datetime.utcnow()
        for allocation in allocations:
            inventory = db.query(EpcInventory).filter(EpcInventory.epc == allocation.epc).first()
            if inventory:
                inventory.status = EpcStatus.SHIPPED
                inventory.last_updated = now
        db.flush()


def create_po_lines(db: Session, order: Order, line_items: list[dict]) -> list[PoLine]:
    lines: list[PoLine] = []
    for item in line_items:
        identification = item.get("item_identification", {})
        line = PoLine(
            order_id=order.id,
            line_number=int(item.get("line_number") or len(lines) + 1),
            gtin_14=str(identification.get("gtin_14", "")).strip(),
            description=identification.get("description"),
            quantity_ordered=int(item.get("quantity_ordered", 0)),
            unit_of_measure=str(item.get("unit_of_measure", "EA")),
        )
        db.add(line)
        lines.append(line)
    db.flush()
    return lines


def record_system_event(
    db: Session,
    event_type: str,
    order_id: int | None = None,
    correlation_id: str | None = None,
    payload: dict | None = None,
) -> SystemEvent:
    event = SystemEvent(
        event_type=event_type,
        order_id=order_id,
        correlation_id=correlation_id,
        payload=json.dumps(payload) if payload else None,
    )
    db.add(event)
    db.flush()
    return event


gtin_epc_resolver = GtinEpcResolver()
