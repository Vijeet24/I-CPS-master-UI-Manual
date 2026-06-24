from sqlalchemy.orm import Session

from app.models import Brand, Category, Product, Subcategory
from app.order_models import EpcInventory, EpcStatus

SAMPLE_GTIN = "00012345678936"
MIN_AVAILABLE_EPCS = 10


def _max_epc_suffix(db: Session, gtin: str) -> int:
    max_suffix = 399
    for row in db.query(EpcInventory).filter(EpcInventory.gtin == gtin).all():
        try:
            max_suffix = max(max_suffix, int(row.epc.rsplit(".", 1)[-1]))
        except ValueError:
            continue
    return max_suffix


def ensure_epc_inventory(db: Session, gtin: str = SAMPLE_GTIN, min_available: int = MIN_AVAILABLE_EPCS) -> int:
    """Ensure at least min_available EPCs are in AVAILABLE status for demo/simulation."""
    available_count = (
        db.query(EpcInventory)
        .filter(EpcInventory.gtin == gtin, EpcInventory.status == EpcStatus.AVAILABLE)
        .count()
    )
    if available_count >= min_available:
        return available_count

    needed = min_available - available_count
    suffix = _max_epc_suffix(db, gtin) + 1
    added = 0
    while added < needed:
        epc = f"urn:epc:id:sgtin:0614141.112345.{suffix}"
        existing = db.query(EpcInventory).filter(EpcInventory.epc == epc).first()
        if existing is None:
            db.add(EpcInventory(epc=epc, gtin=gtin, status=EpcStatus.AVAILABLE))
            added += 1
        suffix += 1
    db.flush()
    return available_count + added


def seed_reference_data(db: Session) -> None:
    brand = db.query(Brand).filter(Brand.brand_name == "MedSupply Co").first()
    if brand is None:
        brand = Brand(
            brand_name="MedSupply Co",
            brand_gln="1234567890123",
            company_prefix="1234567",
            address="100 Healthcare Ave, Boston, MA",
        )
        db.add(brand)
        db.flush()

    sensors = db.query(Category).filter(Category.name == "Sensors").first()
    if sensors is None:
        sensors = Category(name="Sensors")
        db.add(sensors)
        db.flush()

        db.add(Subcategory(name="Oxygen sensor", category_id=sensors.id))
        db.flush()

    subcategory = (
        db.query(Subcategory)
        .filter(Subcategory.name == "Oxygen sensor", Subcategory.category_id == sensors.id)
        .first()
    )

    product = db.query(Product).filter(Product.gtin_14 == SAMPLE_GTIN).first()
    if product is None:
        product = Product(
            gtin_14=SAMPLE_GTIN,
            product_name="Oxygen Sensor",
            description="Medical-grade oxygen sensor for ICU monitoring",
            category_id=sensors.id,
            sub_category_id=subcategory.id if subcategory else None,
            unit_of_measure="EA",
            default_price=129.99,
            currency="USD",
            brand_id=brand.id,
            gs1_digital_link="https://id.gs1.org/01/00012345678936",
        )
        db.add(product)
        db.flush()

    ensure_epc_inventory(db, gtin=SAMPLE_GTIN, min_available=MIN_AVAILABLE_EPCS)
    db.commit()
