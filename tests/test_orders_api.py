import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app import order_models  # noqa: F401

SQLITE_URL = "sqlite://"


@pytest.fixture()
def client():
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.database.SessionLocal", TestingSessionLocal):
        with patch("app.services.order_service.SessionLocal", TestingSessionLocal):
            with patch("app.main.mqtt_service") as mqtt_mock:
                mqtt_mock.connected = False
                mqtt_mock.start = lambda: None
                mqtt_mock.stop = lambda: None
                with patch("app.main.init_db"):
                    with patch("app.main.seed_reference_data"):
                        with patch.object(settings, "mqtt_enabled", False):
                            with patch.object(settings, "fulfillment_mode", "immediate"):
                                with TestClient(app) as test_client:
                                    yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _sample_po() -> dict:
    return {
        "message_id": str(uuid.uuid4()),
        "message_type": "EDI_850_PURCHASE_ORDER",
        "schema_version": "1.0.0",
        "created_at": "2026-05-29T14:13:54.470950+00:00",
        "sender": {"gln": "1514032003830", "name": "IoT-Lab"},
        "receiver": {"gln": "1514250054321", "name": "ICPS-Lab"},
        "payload": {
            "transaction": {"type": "850", "control_number": "000000015", "version": "1.0"},
            "purchase_order": {
                "po_number": f"PO-TEST-{uuid.uuid4().hex[:8]}",
                "po_date": "2026-05-29",
                "currency": "CAD",
            },
            "parties": {
                "buyer": {"gln": "1514032003830"},
                "seller": {"gln": "1514250054321"},
                "ship_to": {"gln": "1514032003830"},
            },
            "line_items": [
                {
                    "line_number": 1,
                    "item_identification": {"gtin_14": "00012345678936", "description": "Oxygen Sensor"},
                    "quantity_ordered": 1,
                    "unit_of_measure": "EA",
                }
            ],
            "totals": {"total_line_items": 1, "total_quantity_ordered": 1},
        },
    }


def test_simulate_purchase_order(client):
    response = client.post("/api/orders/simulate", json={"payload": _sample_po()})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "SHIPPED"
    assert body["acknowledgement"] is not None
    assert body["shipment"] is not None


def test_list_orders_and_stats(client):
    client.post("/api/orders/simulate", json={"payload": _sample_po()})
    orders = client.get("/api/orders").json()
    stats = client.get("/api/orders/stats").json()
    assert len(orders) >= 1
    assert stats["total"] >= 1
    assert stats["shipped"] >= 1


def test_duplicate_po_is_idempotent(client):
    po = _sample_po()
    first = client.post("/api/orders/simulate", json={"payload": po})
    second = client.post("/api/orders/simulate", json={"payload": po})
    assert first.status_code == 201
    assert second.status_code == 201
    orders = client.get("/api/orders").json()
    matching = [item for item in orders if item["correlation_message_id"] == po["message_id"]]
    assert len(matching) == 1


def test_send_audit_message(client):
    client.post("/api/orders/simulate", json={"payload": _sample_po()})
    audit = client.get("/api/orders/audit").json()
    outbound = [entry for entry in audit if entry["direction"] == "OUTBOUND"]
    assert outbound
    ack = next(entry for entry in outbound if "855" in entry["message_type"])
    assert ack["status"] == "GENERATED"

    with patch("app.services.order_service.mqtt_service") as mqtt_mock:
        response = client.post(f"/api/orders/audit/{ack['id']}/send")

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    mqtt_mock.publish_json.assert_called_once()

    audit_after = client.get("/api/orders/audit").json()
    ack_after = next(entry for entry in audit_after if entry["id"] == ack["id"])
    assert ack_after["status"] == "SENT"
