import json
import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.edi.ack_generator import generate_edi_855
from app.edi.asn_generator import generate_edi_856
from app.edi.validators import EdiValidationError, validate_edi_850
from app.mqtt.client import mqtt_service
from app.order_models import MessageDirection, OrderStatus
from app.repository import OrderRepository

logger = logging.getLogger(__name__)

OUTBOUND_TOPICS = {
    "EDI_855_PURCHASE_ORDER_ACK": lambda: settings.mqtt_ack_topic,
    "EDI_856_ADVANCE_SHIP_NOTICE": lambda: settings.mqtt_asn_topic,
}


class OrderService:
    def process_inbound_po(self, payload: dict, source: str = "MQTT") -> dict:
        db = SessionLocal()
        repo = OrderRepository(db)
        correlation_id = payload.get("message_id")

        try:
            if correlation_id and repo.audit_message_exists(correlation_id, MessageDirection.INBOUND):
                logger.info("Duplicate PO ignored", extra={"message_id": correlation_id})
                existing = repo.get_order_by_correlation(correlation_id)
                db.commit()
                return {
                    "status": "duplicate",
                    "order_id": existing.id if existing else None,
                    "message_id": correlation_id,
                }

            parsed = validate_edi_850(payload)
            correlation_id = parsed["message_id"]

            existing_order = repo.get_order_by_correlation(correlation_id)
            if existing_order:
                db.commit()
                return {"status": "duplicate", "order_id": existing_order.id, "message_id": correlation_id}

            repo.record_audit(
                message_id=correlation_id,
                message_type="EDI_850_PURCHASE_ORDER",
                direction=MessageDirection.INBOUND,
                payload=payload,
                status="RECEIVED",
                correlation_id=correlation_id,
            )

            order = repo.create_order(
                po_number=parsed["po_number"],
                buyer_id=parsed["buyer_id"],
                seller_id=parsed.get("seller_id") or settings.seller_gln,
                correlation_message_id=correlation_id,
                raw_po_json=json.dumps(payload),
            )

            ack_payload = generate_edi_855(
                payload,
                parsed,
                settings.seller_gln,
                settings.seller_name,
                parsed["buyer_id"],
                payload.get("sender", {}).get("name") or settings.buyer_name,
            )
            repo.create_acknowledgement(
                order.id,
                ack_payload["message_id"],
                json.dumps(ack_payload),
            )
            repo.update_order_status(order, OrderStatus.ACKNOWLEDGED)
            repo.record_audit(
                message_id=ack_payload["message_id"],
                message_type="EDI_855_PURCHASE_ORDER_ACK",
                direction=MessageDirection.OUTBOUND,
                payload=ack_payload,
                status="GENERATED",
                correlation_id=correlation_id,
            )

            repo.commit()
            self._schedule_fulfillment(order.id, correlation_id)
            return {"status": "processed", "order_id": order.id, "message_id": correlation_id}
        except EdiValidationError as exc:
            repo.rollback()
            if correlation_id:
                with SessionLocal() as error_db:
                    error_repo = OrderRepository(error_db)
                    error_repo.record_audit(
                        message_id=correlation_id,
                        message_type="EDI_850_PURCHASE_ORDER",
                        direction=MessageDirection.INBOUND,
                        payload=payload,
                        status="VALIDATION_FAILED",
                        correlation_id=correlation_id,
                    )
                    error_repo.commit()
            raise
        except Exception:
            repo.rollback()
            raise
        finally:
            db.close()

    def _schedule_fulfillment(self, order_id: int, correlation_id: str) -> None:
        delay = 0
        if settings.fulfillment_mode == "simulated":
            delay = settings.fulfillment_delay_seconds
        elif settings.fulfillment_mode == "scheduled":
            delay = settings.fulfillment_delay_seconds

        if delay <= 0:
            self.complete_fulfillment(order_id, correlation_id)
            return

        timer = threading.Timer(delay, self.complete_fulfillment, args=(order_id, correlation_id))
        timer.daemon = True
        timer.start()

    def complete_fulfillment(self, order_id: int, correlation_id: str) -> None:
        db = SessionLocal()
        repo = OrderRepository(db)
        try:
            order = repo.get_order_by_id(order_id)
            if order is None or order.status == OrderStatus.SHIPPED:
                return

            po_message = json.loads(order.raw_po_json)
            parsed = {
                "message_id": order.correlation_message_id,
                "po_number": order.po_number,
                "buyer_id": order.buyer_id,
            }

            repo.update_order_status(order, OrderStatus.READY_TO_SHIP)
            asn_payload = generate_edi_856(
                po_message,
                parsed,
                settings.seller_gln,
                settings.seller_name,
                order.buyer_id,
                po_message.get("sender", {}).get("name") or settings.buyer_name,
                settings.default_carrier,
            )
            shipment_data = asn_payload["payload"]["shipment"]
            repo.create_shipment(
                order_id=order.id,
                shipment_id=shipment_data["shipment_id"],
                tracking_number=shipment_data["tracking_number"],
                carrier=shipment_data["carrier"],
                ship_date=datetime.fromisoformat(shipment_data["ship_date"]),
                raw_856_json=json.dumps(asn_payload),
            )
            repo.update_order_status(order, OrderStatus.SHIPPED)
            repo.record_audit(
                message_id=asn_payload["message_id"],
                message_type="EDI_856_ADVANCE_SHIP_NOTICE",
                direction=MessageDirection.OUTBOUND,
                payload=asn_payload,
                status="GENERATED",
                correlation_id=correlation_id,
            )

            repo.commit()
            logger.info("Order fulfilled and ASN sent", extra={"order_id": order_id})
        except Exception:
            repo.rollback()
            logger.exception("Fulfillment failed for order %s", order_id)
        finally:
            db.close()

    def force_ship(self, order_id: int) -> dict:
        db = SessionLocal()
        repo = OrderRepository(db)
        try:
            order = repo.get_order_by_id(order_id)
            if order is None:
                raise ValueError("Order not found")
            if order.status == OrderStatus.SHIPPED:
                return {"status": "already_shipped", "order_id": order_id}
            repo.commit()
        finally:
            db.close()

        self.complete_fulfillment(order_id, order.correlation_message_id)
        return {"status": "shipped", "order_id": order_id}

    def send_audit_message(self, audit_id: int) -> dict:
        db = SessionLocal()
        repo = OrderRepository(db)
        try:
            entry = repo.get_audit_by_id(audit_id)
            if entry is None:
                raise ValueError("Audit entry not found")
            if entry.direction != MessageDirection.OUTBOUND:
                raise ValueError("Only outbound messages can be sent")
            if entry.status == "SENT":
                return {
                    "status": "already_sent",
                    "audit_id": audit_id,
                    "message_id": entry.message_id,
                }

            topic_factory = OUTBOUND_TOPICS.get(entry.message_type)
            if topic_factory is None:
                raise ValueError(f"Unsupported outbound message type: {entry.message_type}")

            payload = json.loads(entry.payload)
            topic = topic_factory()
            mqtt_service.publish_json(topic, payload)
            repo.update_audit_status(entry, "SENT")
            repo.commit()
            logger.info(
                "Outbound audit message sent manually",
                extra={"audit_id": audit_id, "message_id": entry.message_id, "topic": topic},
            )
            return {
                "status": "sent",
                "audit_id": audit_id,
                "message_id": entry.message_id,
                "topic": topic,
            }
        except Exception:
            repo.rollback()
            raise
        finally:
            db.close()


order_service = OrderService()
