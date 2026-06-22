import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import SessionLocal, init_db
from app.mqtt.client import mqtt_service
from app.routers import asn, brands, categories, dashboard, orders, products, purchase_orders, rfid, ws
from app.seed import seed_reference_data
from app.services.order_service import order_service

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )


def _handle_mqtt_message(_topic: str, payload: dict) -> None:
    order_service.process_inbound_po(payload, source="MQTT")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _configure_logging()
    init_db()
    db = SessionLocal()
    try:
        seed_reference_data(db)
    finally:
        db.close()

    mqtt_service.set_message_handler(_handle_mqtt_message)
    mqtt_service.start()
    yield
    mqtt_service.stop()


app = FastAPI(title="ICPS Master UI", version="2.0.0", lifespan=lifespan)

app.include_router(brands.router)
app.include_router(categories.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(dashboard.router)
app.include_router(rfid.router)
app.include_router(asn.router)
app.include_router(purchase_orders.router)
app.include_router(ws.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
