import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class OrderStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PICKING = "PICKING"
    ALLOCATED = "ALLOCATED"
    VERIFIED = "VERIFIED"
    ASN_SENT = "ASN_SENT"


class MessageDirection(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class EpcStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"


class VerificationResult(str, enum.Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    po_number = Column(String(64), nullable=False, index=True)
    buyer_id = Column(String(13), nullable=False, index=True)
    seller_id = Column(String(13), nullable=True)
    correlation_message_id = Column(String(64), nullable=False, unique=True, index=True)
    received_timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.RECEIVED, nullable=False, index=True)
    raw_po_json = Column(Text, nullable=False)

    po_lines = relationship("PoLine", back_populates="order", cascade="all, delete-orphan")
    acknowledgement = relationship(
        "Acknowledgement", back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    shipment = relationship(
        "Shipment", back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    epc_allocations = relationship(
        "EpcAllocation", back_populates="order", cascade="all, delete-orphan"
    )
    rfid_scans = relationship("RfidScan", back_populates="order", cascade="all, delete-orphan")


class PoLine(Base):
    __tablename__ = "po_lines"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number = Column(Integer, nullable=False)
    gtin_14 = Column(String(14), nullable=False, index=True)
    description = Column(String(255), nullable=True)
    quantity_ordered = Column(Integer, nullable=False)
    unit_of_measure = Column(String(50), nullable=False)

    order = relationship("Order", back_populates="po_lines")
    epc_allocations = relationship("EpcAllocation", back_populates="po_line")


class Acknowledgement(Base):
    __tablename__ = "acknowledgements"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    message_id = Column(String(64), nullable=False, unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    raw_855_json = Column(Text, nullable=False)

    order = relationship("Order", back_populates="acknowledgement")


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    asn_number = Column(String(64), nullable=True, index=True)
    shipment_id = Column(String(64), nullable=False, unique=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    tracking_number = Column(String(64), nullable=False)
    carrier = Column(String(128), nullable=False)
    ship_date = Column(DateTime, nullable=False)
    delivery_date = Column(DateTime, nullable=True)
    raw_856_json = Column(Text, nullable=False)

    order = relationship("Order", back_populates="shipment")


class EpcInventory(Base):
    __tablename__ = "epc_inventory"

    id = Column(Integer, primary_key=True, index=True)
    epc = Column(String(255), nullable=False, unique=True, index=True)
    gtin = Column(String(14), nullable=False, index=True)
    status = Column(Enum(EpcStatus), default=EpcStatus.AVAILABLE, nullable=False, index=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EpcAllocation(Base):
    __tablename__ = "epc_allocations"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    po_line_id = Column(Integer, ForeignKey("po_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    epc = Column(String(255), nullable=False, index=True)
    gtin = Column(String(14), nullable=False, index=True)
    allocated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    order = relationship("Order", back_populates="epc_allocations")
    po_line = relationship("PoLine", back_populates="epc_allocations")


class RfidScan(Base):
    __tablename__ = "rfid_scans"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_session_id = Column(String(64), nullable=False, index=True)
    expected_epcs = Column(Text, nullable=False)
    scanned_epcs = Column(Text, nullable=True)
    matched_epcs = Column(Text, nullable=True)
    missing_epcs = Column(Text, nullable=True)
    unexpected_epcs = Column(Text, nullable=True)
    result = Column(Enum(VerificationResult), default=VerificationResult.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    order = relationship("Order", back_populates="rfid_scans")


class MessageAudit(Base):
    __tablename__ = "message_audit"
    __table_args__ = (UniqueConstraint("message_id", "direction", name="uq_message_audit_id_direction"),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(64), nullable=False, index=True)
    message_type = Column(String(64), nullable=False, index=True)
    direction = Column(Enum(MessageDirection), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    payload = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="PROCESSED")
    correlation_id = Column(String(64), nullable=True, index=True)
    topic = Column(String(255), nullable=True)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    payload = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
