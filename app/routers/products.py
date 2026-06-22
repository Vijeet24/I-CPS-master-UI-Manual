from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Brand, Category, Product, Subcategory
from app.order_models import EpcInventory, EpcStatus
from app.schemas import ProductCreate, ProductResponse, ProductUpdate
from app.services.product_import import export_products_csv, import_products, validate_import_rows

router = APIRouter(prefix="/api/products", tags=["products"])


def _category_path(category_name: str | None, subcategory_name: str | None) -> str | None:
    if category_name and subcategory_name:
        return f"{category_name}/{subcategory_name}"
    return category_name


def _serialize_product(product: Product) -> ProductResponse:
    category_name = product.category.name if product.category else None
    subcategory_name = product.sub_category.name if product.sub_category else None
    return ProductResponse(
        id=product.id,
        gtin_14=product.gtin_14,
        product_name=product.product_name,
        description=product.description,
        category_id=product.category_id,
        sub_category_id=product.sub_category_id,
        unit_of_measure=product.unit_of_measure,
        default_price=product.default_price,
        currency=product.currency,
        brand_id=product.brand_id,
        gs1_digital_link=product.gs1_digital_link,
        brand_name=product.brand.brand_name,
        category_name=category_name,
        sub_category_name=subcategory_name,
        category_path=_category_path(category_name, subcategory_name),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def _validate_relationships(
    db: Session,
    brand_id: int,
    category_id: int | None,
    sub_category_id: int | None,
) -> None:
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")

    if category_id is not None:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    if sub_category_id is not None:
        subcategory = db.query(Subcategory).filter(Subcategory.id == sub_category_id).first()
        if not subcategory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Subcategory not found"
            )
        if category_id is not None and subcategory.category_id != category_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subcategory does not belong to the selected category",
            )
        if category_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category is required when a subcategory is selected",
            )


@router.get("", response_model=list[ProductResponse])
def list_products(db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .options(
            joinedload(Product.brand),
            joinedload(Product.category),
            joinedload(Product.sub_category),
        )
        .order_by(Product.product_name)
        .all()
    )
    return [_serialize_product(product) for product in products]


class ImportPreviewResponse(BaseModel):
    imported_count: int
    failed_count: int
    rows: list[dict]


@router.post("/import/preview", response_model=ImportPreviewResponse)
async def preview_product_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = (await file.read()).decode("utf-8-sig")
    preview = validate_import_rows(db, content)
    return ImportPreviewResponse(
        imported_count=preview.imported_count,
        failed_count=preview.failed_count,
        rows=[
            {"row_number": row.row_number, "data": row.data, "valid": row.valid, "errors": row.errors}
            for row in preview.rows
        ],
    )


@router.post("/import", response_model=ImportPreviewResponse)
async def import_product_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = (await file.read()).decode("utf-8-sig")
    preview = import_products(db, content)
    if preview.failed_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Import rejected due to validation errors",
                "failed_count": preview.failed_count,
                "rows": [
                    {"row_number": row.row_number, "errors": row.errors}
                    for row in preview.rows
                    if not row.valid
                ],
            },
        )
    return ImportPreviewResponse(
        imported_count=preview.imported_count,
        failed_count=preview.failed_count,
        rows=[],
    )


@router.get("/export")
def export_products(db: Session = Depends(get_db)):
    csv_content = export_products_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="products.csv"'},
    )


class EpcInventoryResponse(BaseModel):
    id: int
    epc: str
    gtin: str
    status: str
    last_updated: str


@router.get("/epc-inventory", response_model=list[EpcInventoryResponse])
def list_epc_inventory(
    gtin: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(EpcInventory)
    if gtin:
        query = query.filter(EpcInventory.gtin == gtin)
    if status:
        query = query.filter(EpcInventory.status == EpcStatus(status))
    rows = query.order_by(EpcInventory.gtin, EpcInventory.epc).all()
    return [
        EpcInventoryResponse(
            id=row.id,
            epc=row.epc,
            gtin=row.gtin,
            status=row.status.value,
            last_updated=row.last_updated.isoformat(),
        )
        for row in rows
    ]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = (
        db.query(Product)
        .options(
            joinedload(Product.brand),
            joinedload(Product.category),
            joinedload(Product.sub_category),
        )
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _serialize_product(product)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    existing = db.query(Product).filter(Product.gtin_14 == payload.gtin_14).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A product with this GTIN-14 already exists",
        )

    _validate_relationships(
        db, payload.brand_id, payload.category_id, payload.sub_category_id
    )

    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)

    product = (
        db.query(Product)
        .options(
            joinedload(Product.brand),
            joinedload(Product.category),
            joinedload(Product.sub_category),
        )
        .filter(Product.id == product.id)
        .first()
    )
    return _serialize_product(product)


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    data = payload.model_dump(exclude_unset=True)

    if "gtin_14" in data:
        duplicate = (
            db.query(Product)
            .filter(Product.gtin_14 == data["gtin_14"], Product.id != product_id)
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A product with this GTIN-14 already exists",
            )

    brand_id = data.get("brand_id", product.brand_id)
    category_id = data.get("category_id", product.category_id)
    sub_category_id = data.get("sub_category_id", product.sub_category_id)

    if "category_id" in data and data["category_id"] is None:
        sub_category_id = None
        data["sub_category_id"] = None

    _validate_relationships(db, brand_id, category_id, sub_category_id)

    for key, value in data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)

    product = (
        db.query(Product)
        .options(
            joinedload(Product.brand),
            joinedload(Product.category),
            joinedload(Product.sub_category),
        )
        .filter(Product.id == product.id)
        .first()
    )
    return _serialize_product(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    db.delete(product)
    db.commit()

