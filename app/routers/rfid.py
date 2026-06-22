from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.repository import OrderRepository
from app.schemas_orders import RfidScanResponse, RfidStartScanRequest, RfidVerifyRequest
from app.services.rfid_service import RfidServiceError, rfid_service
from app.services.workflow_ui import serialize_order_detail

router = APIRouter(prefix="/api/rfid", tags=["rfid"])


def _serialize_scan(scan) -> RfidScanResponse:
    import json

    def _load(value):
        if not value:
            return []
        return json.loads(value)

    return RfidScanResponse(
        id=scan.id,
        scan_session_id=scan.scan_session_id,
        expected_epcs=_load(scan.expected_epcs),
        scanned_epcs=_load(scan.scanned_epcs),
        matched_epcs=_load(scan.matched_epcs),
        missing_epcs=_load(scan.missing_epcs),
        unexpected_epcs=_load(scan.unexpected_epcs),
        result=scan.result.value,
        created_at=scan.created_at,
    )


@router.post("/start-scan", response_model=RfidScanResponse)
def start_rfid_scan(body: RfidStartScanRequest, db: Session = Depends(get_db)):
    try:
        scan = rfid_service.start_scan(db, body.order_id, rescan=body.rescan)
        repo = OrderRepository(db)
        repo.commit()
        return _serialize_scan(scan)
    except RfidServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.post("/verify", response_model=RfidScanResponse)
def verify_rfid_scan(body: RfidVerifyRequest, db: Session = Depends(get_db)):
    try:
        scan = rfid_service.verify(db, body.order_id, body.scan_session_id)
        repo = OrderRepository(db)
        repo.commit()
        return _serialize_scan(scan)
    except RfidServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc


@router.get("/results/{order_id}", response_model=RfidScanResponse | None)
def get_rfid_results(order_id: int, db: Session = Depends(get_db)):
    scan = rfid_service.get_latest_result(db, order_id)
    if scan is None:
        return None
    return _serialize_scan(scan)
