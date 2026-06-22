import uuid
from datetime import datetime, timezone
from typing import Any


def generate_edi_856(
    po_message: dict,
    parsed: dict,
    seller_gln: str,
    seller_name: str,
    buyer_gln: str,
    buyer_name: str,
    carrier: str,
    epc_by_gtin: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    payload = po_message.get("payload", {})
    line_items = payload.get("line_items", [])
    shipment_id = f"SHP-{uuid.uuid4().hex[:12].upper()}"
    asn_number = f"ASN-{uuid.uuid4().hex[:10].upper()}"
    tracking_number = f"TRK{uuid.uuid4().hex[:10].upper()}"
    ship_date = datetime.now(timezone.utc).isoformat()
    delivery_date = datetime.now(timezone.utc).isoformat()

    shipped_lines = []
    for item in line_items:
        gtin = item.get("item_identification", {}).get("gtin_14")
        line_payload = {
            "po_line_number": item.get("line_number"),
            "item_identification": item.get("item_identification", {}),
            "quantity_shipped": item.get("quantity_ordered"),
            "unit_of_measure": item.get("unit_of_measure"),
        }
        if epc_by_gtin and gtin in epc_by_gtin:
            line_payload["epcs"] = epc_by_gtin[gtin]
        shipped_lines.append(line_payload)

    return {
        "message_id": f"MSG-856-{uuid.uuid4()}",
        "message_type": "EDI_856_ADVANCE_SHIP_NOTICE",
        "schema_version": "1.0.0",
        "created_at": ship_date,
        "sender": {"gln": seller_gln, "name": seller_name},
        "receiver": {"gln": buyer_gln, "name": buyer_name},
        "correlation_id": parsed["message_id"],
        "payload": {
            "transaction": {
                "type": "856",
                "control_number": payload.get("transaction", {}).get("control_number", "000000001"),
                "version": "1.0",
            },
            "shipment": {
                "asn_number": asn_number,
                "shipment_id": shipment_id,
                "carrier": carrier,
                "tracking_number": tracking_number,
                "ship_date": ship_date,
                "delivery_date": delivery_date,
                "po_number": parsed["po_number"],
                "order_reference": parsed["message_id"],
            },
            "parties": {
                "buyer": {"gln": buyer_gln},
                "seller": {"gln": seller_gln},
                "ship_to": payload.get("parties", {}).get("ship_to", {"gln": buyer_gln}),
            },
            "line_items": shipped_lines,
        },
    }
