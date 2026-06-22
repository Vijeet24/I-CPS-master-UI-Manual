from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.repository import OrderRepository
from app.schemas_orders import AsnTrackingResponse, DashboardMetricsResponse

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetricsResponse)
def get_dashboard_metrics(db: Session = Depends(get_db)):
    metrics = OrderRepository(db).get_dashboard_metrics()
    return DashboardMetricsResponse(**metrics)


@router.get("/asn-tracking", response_model=list[AsnTrackingResponse])
def get_asn_tracking(limit: int = 50, db: Session = Depends(get_db)):
    shipments = OrderRepository(db).list_asn_tracking(limit=limit)
    results = []
    for shipment in shipments:
        order = shipment.order
        results.append(
            AsnTrackingResponse(
                asn_number=shipment.asn_number,
                po_number=order.po_number if order else "—",
                shipment_status="SENT",
                carrier=shipment.carrier,
                asn_sent_time=shipment.ship_date,
                total_epcs=len(order.epc_allocations) if order else 0,
            )
        )
    return results
