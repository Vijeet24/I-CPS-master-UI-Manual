import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.edi.ack_generator import generate_edi_855
from app.edi.asn_generator import generate_edi_856
from app.edi.validators import EdiValidationError, validate_edi_850
from app.mqtt.client import mqtt_service
from app.order_models import MessageDirection, OrderStatus, VerificationResult
from app.repository import OrderRepository
from app.services.event_bus import event_bus
from app.services.gtin_epc_resolver import (
    GtinEpcResolverError,
    create_po_lines,
    gtin_epc_resolver,
    record_system_event,
)
from app.services.rfid_service import rfid_service

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
                topic=settings.mqtt_subscribe_topic if source == "MQTT" else None,
            )

            order = repo.create_order(
                po_number=parsed["po_number"],
                buyer_id=parsed["buyer_id"],
                seller_id=parsed.get("seller_id") or settings.seller_gln,
                correlation_message_id=correlation_id,
                raw_po_json=json.dumps(payload),
            )
            create_po_lines(db, order, parsed["line_items"])
            record_system_event(
                db,
                "PO_RECEIVED",
                order_id=order.id,
                correlation_id=correlation_id,
                payload={"po_number": order.po_number, "source": source},
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
                topic=settings.mqtt_ack_topic,
            )
            record_system_event(
                db,
                "PO_ACKNOWLEDGED",
                order_id=order.id,
                correlation_id=correlation_id,
                payload={"ack_message_id": ack_payload["message_id"]},
            )

            self._prepare_order(db, repo, order)

            repo.commit()
            event_bus.publish("order_updated", {"order_id": order.id, "status": order.status.value})
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
        except GtinEpcResolverError as exc:
            repo.rollback()
            logger.error("EPC allocation failed: %s", exc.message)
            raise ValueError(exc.message) from exc
        except Exception:
            repo.rollback()
            raise
        finally:
            db.close()

    def _prepare_order(self, db: Session, repo: OrderRepository, order) -> None:
        repo.update_order_status(order, OrderStatus.PICKING)
        record_system_event(
            db,
            "ORDER_PICKING",
            order_id=order.id,
            correlation_id=order.correlation_message_id,
        )
        gtin_epc_resolver.allocate_for_order(db, order)
        repo.update_order_status(order, OrderStatus.ALLOCATED)
        record_system_event(
            db,
            "EPC_ALLOCATED",
            order_id=order.id,
            correlation_id=order.correlation_message_id,
            payload={"epc_count": len(order.epc_allocations)},
        )

    def generate_asn(self, order_id: int) -> dict:
        db = SessionLocal()
        repo = OrderRepository(db)
        try:
            order = repo.get_order_by_id(order_id)
            if order is None:
                raise ValueError("Order not found")
            if order.status != OrderStatus.VERIFIED:
                raise ValueError(
                    f"ASN cannot be generated until RFID verification passes (status: {order.status.value})"
                )
            if order.shipment is not None:
                return {"status": "already_sent", "order_id": order_id}

            po_message = json.loads(order.raw_po_json)
            parsed = {
                "message_id": order.correlation_message_id,
                "po_number": order.po_number,
                "buyer_id": order.buyer_id,
            }
            allocations = gtin_epc_resolver.get_allocated_epcs(db, order_id)
            epc_by_gtin: dict[str, list[str]] = {}
            for allocation in order.epc_allocations:
                epc_by_gtin.setdefault(allocation.gtin, []).append(allocation.epc)

            asn_payload = generate_edi_856(
                po_message,
                parsed,
                settings.seller_gln,
                settings.seller_name,
                order.buyer_id,
                po_message.get("sender", {}).get("name") or settings.buyer_name,
                settings.default_carrier,
                epc_by_gtin=epc_by_gtin,
            )
            shipment_data = asn_payload["payload"]["shipment"]
            repo.create_shipment(
                order_id=order.id,
                shipment_id=shipment_data["shipment_id"],
                tracking_number=shipment_data["tracking_number"],
                carrier=shipment_data["carrier"],
                ship_date=datetime.fromisoformat(shipment_data["ship_date"]),
                raw_856_json=json.dumps(asn_payload),
                asn_number=shipment_data.get("asn_number"),
                delivery_date=(
                    datetime.fromisoformat(shipment_data["delivery_date"])
                    if shipment_data.get("delivery_date")
                    else None
                ),
            )
            gtin_epc_resolver.mark_shipped(db, order_id)
            repo.update_order_status(order, OrderStatus.ASN_SENT)
            repo.record_audit(
                message_id=asn_payload["message_id"],
                message_type="EDI_856_ADVANCE_SHIP_NOTICE",
                direction=MessageDirection.OUTBOUND,
                payload=asn_payload,
                status="GENERATED",
                correlation_id=order.correlation_message_id,
                topic=settings.mqtt_asn_topic,
            )
            record_system_event(
                db,
                "ASN_GENERATED",
                order_id=order.id,
                correlation_id=order.correlation_message_id,
                payload={"asn_number": shipment_data.get("asn_number")},
            )
            repo.commit()
            event_bus.publish("asn_generated", {"order_id": order_id})
            return {"status": "generated", "order_id": order_id, "message_id": asn_payload["message_id"]}
        except Exception:
            repo.rollback()
            raise
        finally:
            db.close()

    def complete_rfid_and_asn(self, order_id: int) -> dict:
        db = SessionLocal()
        try:
            rfid_service.start_scan(db, order_id)
            scan = rfid_service.verify(db, order_id)
            repo = OrderRepository(db)
            repo.commit()
        finally:
            db.close()

        if scan.result != VerificationResult.PASS:
            return {"status": "verification_failed", "order_id": order_id}

        return self.generate_asn(order_id)

    def force_ship(self, order_id: int) -> dict:
        return self.complete_rfid_and_asn(order_id)

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
            topic = entry.topic or topic_factory()
            mqtt_service.publish_json(topic, payload)
            repo.update_audit_status(entry, "SENT")
            repo.commit()
            event_bus.publish("mqtt_message_sent", {"audit_id": audit_id, "topic": topic})
            logger.info(
                "Outbound audit message sent",
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
