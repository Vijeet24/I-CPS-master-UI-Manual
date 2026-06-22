import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Brand, Category, Product, Subcategory

CSV_COLUMNS = [
    "gtin_14",
    "product_name",
    "description",
    "category_path",
    "category",
    "sub_category",
    "unit_of_measure",
    "default_price",
    "currency",
    "brand_name",
    "gs1_digital_link",
]

GS1_LINK_PATTERN = re.compile(r"^https://id\.gs1\.org/.+", re.IGNORECASE)


@dataclass
class ImportPreviewRow:
    row_number: int
    data: dict
    valid: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportPreviewResult:
    rows: list[ImportPreviewRow]
    imported_count: int = 0
    failed_count: int = 0


def _parse_category_path(category_path: str | None, category: str | None, sub_category: str | None):
    if category_path and "/" in category_path:
        parts = category_path.split("/", 1)
        return parts[0].strip() or None, parts[1].strip() or None
    return (category or None), (sub_category or None)


def _resolve_brand(db: Session, brand_name: str) -> Brand:
    brand = db.query(Brand).filter(Brand.brand_name == brand_name).first()
    if brand is None:
        brand = Brand(brand_name=brand_name)
        db.add(brand)
        db.flush()
    return brand


def _resolve_category(db: Session, category_name: str | None, subcategory_name: str | None):
    category_id = None
    sub_category_id = None
    if not category_name:
        return category_id, sub_category_id

    category = db.query(Category).filter(Category.name == category_name).first()
    if category is None:
        category = Category(name=category_name)
        db.add(category)
        db.flush()

    category_id = category.id
    if subcategory_name:
        subcategory = (
            db.query(Subcategory)
            .filter(Subcategory.name == subcategory_name, Subcategory.category_id == category.id)
            .first()
        )
        if subcategory is None:
            subcategory = Subcategory(name=subcategory_name, category_id=category.id)
            db.add(subcategory)
            db.flush()
        sub_category_id = subcategory.id
    return category_id, sub_category_id


def validate_import_rows(db: Session, file_content: str) -> ImportPreviewResult:
    reader = csv.DictReader(io.StringIO(file_content))
    if reader.fieldnames is None:
        return ImportPreviewResult(rows=[], failed_count=1)

    rows: list[ImportPreviewRow] = []
    seen_gtins: set[str] = set()
    imported = 0
    failed = 0

    for index, raw in enumerate(reader, start=2):
        data = {column: (raw.get(column) or "").strip() for column in CSV_COLUMNS}
        errors: list[str] = []

        if not data["gtin_14"]:
            errors.append("GTIN is mandatory")
        if not data["product_name"]:
            errors.append("Product Name is mandatory")
        if not data["brand_name"]:
            errors.append("Brand is mandatory")
        if not data["currency"]:
            errors.append("Currency is mandatory")
        if data["gs1_digital_link"] and not GS1_LINK_PATTERN.match(data["gs1_digital_link"]):
            errors.append("Invalid GS1 Digital Link format")

        gtin = data["gtin_14"]
        if gtin:
            if gtin in seen_gtins:
                errors.append("Duplicate GTIN in file")
            seen_gtins.add(gtin)
            existing = db.query(Product).filter(Product.gtin_14 == gtin).first()
            if existing:
                errors.append("GTIN already exists in catalog")

        valid = not errors
        if valid:
            imported += 1
        else:
            failed += 1
        rows.append(ImportPreviewRow(row_number=index, data=data, valid=valid, errors=errors))

    return ImportPreviewResult(rows=rows, imported_count=imported, failed_count=failed)


def import_products(db: Session, file_content: str, commit: bool = True) -> ImportPreviewResult:
    preview = validate_import_rows(db, file_content)
    if preview.failed_count:
        return preview

    for row in preview.rows:
        data = row.data
        brand = _resolve_brand(db, data["brand_name"])
        category_name, subcategory_name = _parse_category_path(
            data["category_path"], data["category"], data["sub_category"]
        )
        category_id, sub_category_id = _resolve_category(db, category_name, subcategory_name)
        product = Product(
            gtin_14=data["gtin_14"],
            product_name=data["product_name"],
            description=data["description"] or None,
            category_id=category_id,
            sub_category_id=sub_category_id,
            unit_of_measure=data["unit_of_measure"] or "EA",
            default_price=float(data["default_price"]) if data["default_price"] else None,
            currency=data["currency"].upper(),
            brand_id=brand.id,
            gs1_digital_link=data["gs1_digital_link"] or None,
        )
        db.add(product)

    if commit:
        db.commit()
    else:
        db.flush()
    return preview


def export_products_csv(db: Session) -> str:
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

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for product in products:
        category_name = product.category.name if product.category else ""
        subcategory_name = product.sub_category.name if product.sub_category else ""
        category_path = f"{category_name}/{subcategory_name}" if category_name and subcategory_name else category_name
        writer.writerow(
            {
                "gtin_14": product.gtin_14,
                "product_name": product.product_name,
                "description": product.description or "",
                "category_path": category_path or "",
                "category": category_name or "",
                "sub_category": subcategory_name or "",
                "unit_of_measure": product.unit_of_measure,
                "default_price": str(product.default_price) if product.default_price is not None else "",
                "currency": product.currency,
                "brand_name": product.brand.brand_name,
                "gs1_digital_link": product.gs1_digital_link or "",
            }
        )
    return output.getvalue()
