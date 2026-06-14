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
    shipment_id: str
    tracking_number: str
    carrier: str
    ship_date: datetime
    raw_856_json: str


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
    workflow_steps: list[WorkflowStepResponse] = Field(default_factory=list)


class WorkflowStatsResponse(BaseModel):
    total: int = 0
    received: int = 0
    acknowledged: int = 0
    ready_to_ship: int = 0
    shipped: int = 0


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
