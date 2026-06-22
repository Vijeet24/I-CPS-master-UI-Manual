from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_number: str
    buyer_id: str
    seller_id: Optional[str] = None
    correlation_message_id: str
    received_timestamp: datetime
    status: str
    line_item_count: int = 0
    gtin_count: int = 0
    epc_count: int = 0
    verification_result: Optional[str] = None
    asn_status: str = "PENDING"
    has_acknowledgement: bool = False
    has_shipment: bool = False


class AcknowledgementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: str
    timestamp: datetime
    raw_855_json: str


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asn_number: Optional[str] = None
    shipment_id: str
    tracking_number: str
    carrier: str
    ship_date: datetime
    delivery_date: Optional[datetime] = None
    raw_856_json: str


class EpcAllocationResponse(BaseModel):
    id: int
    gtin: str
    epc: str
    po_line_id: int
    allocated_at: datetime


class RfidScanResponse(BaseModel):
    id: int
    scan_session_id: str
    expected_epcs: list[str] = Field(default_factory=list)
    scanned_epcs: list[str] = Field(default_factory=list)
    matched_epcs: list[str] = Field(default_factory=list)
    missing_epcs: list[str] = Field(default_factory=list)
    unexpected_epcs: list[str] = Field(default_factory=list)
    result: str
    created_at: datetime


class MessageAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: str
    message_type: str
    direction: str
    timestamp: datetime
    payload: str
    status: str
    correlation_id: Optional[str] = None
    topic: Optional[str] = None


class WorkflowStepResponse(BaseModel):
    step: int
    name: str
    status: str
    completed: bool
    timestamp: Optional[datetime] = None
    description: str


class OrderDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_number: str
    buyer_id: str
    seller_id: Optional[str] = None
    correlation_message_id: str
    received_timestamp: datetime
    status: str
    raw_po_json: str
    acknowledgement: Optional[AcknowledgementResponse] = None
    shipment: Optional[ShipmentResponse] = None
    epc_allocations: list[EpcAllocationResponse] = Field(default_factory=list)
    rfid_scan: Optional[RfidScanResponse] = None
    workflow_steps: list[WorkflowStepResponse] = Field(default_factory=list)


class WorkflowStatsResponse(BaseModel):
    total: int = 0
    received: int = 0
    acknowledged: int = 0
    picking: int = 0
    allocated: int = 0
    verified: int = 0
    asn_sent: int = 0
    verification_failures: int = 0


class DashboardMetricsResponse(BaseModel):
    purchase_orders_received: int = 0
    po_acknowledgements_sent: int = 0
    orders_in_preparation: int = 0
    rfid_verification_failures: int = 0
    asn_sent: int = 0
    total_products: int = 0
    total_epcs_available: int = 0
    pipeline: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class MqttStatusResponse(BaseModel):
    enabled: bool
    connected: bool
    broker: str
    port: int
    subscribe_topic: str
    ack_topic: str
    asn_topic: str


class SimulatePurchaseOrderRequest(BaseModel):
    payload: dict


class SendAuditMessageResponse(BaseModel):
    status: str
    audit_id: int
    message_id: str
    topic: Optional[str] = None


class RfidStartScanRequest(BaseModel):
    order_id: int
    rescan: bool = False


class RfidVerifyRequest(BaseModel):
    order_id: int
    scan_session_id: Optional[str] = None


class AsnGenerateRequest(BaseModel):
    order_id: int


class PurchaseOrderRequest(BaseModel):
    payload: dict


class AsnTrackingResponse(BaseModel):
    asn_number: Optional[str]
    po_number: str
    shipment_status: str
    carrier: str
    asn_sent_time: datetime
    total_epcs: int
