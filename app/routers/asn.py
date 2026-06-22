from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.repository import OrderRepository
from app.schemas_orders import AsnGenerateRequest, OrderDetailResponse
from app.services.order_service import order_service
from app.services.workflow_ui import serialize_order_detail

router = APIRouter(prefix="/api/asn", tags=["asn"])


@router.post("/generate", response_model=OrderDetailResponse)
def generate_asn(body: AsnGenerateRequest, db: Session = Depends(get_db)):
    try:
        result = order_service.generate_asn(body.order_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    order = OrderRepository(db).get_order_by_id(result["order_id"])
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return serialize_order_detail(order)
