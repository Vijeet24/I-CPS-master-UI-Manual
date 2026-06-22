from sqlalchemy.orm import Session

from app.models import Brand, Category, Product, Subcategory
from app.order_models import EpcInventory, EpcStatus


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

    sample_gtin = "00012345678936"
    product = db.query(Product).filter(Product.gtin_14 == sample_gtin).first()
    if product is None:
        product = Product(
            gtin_14=sample_gtin,
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

    for suffix in range(400, 405):
        epc = f"urn:epc:id:sgtin:0614141.112345.{suffix}"
        existing = db.query(EpcInventory).filter(EpcInventory.epc == epc).first()
        if existing is None:
            db.add(EpcInventory(epc=epc, gtin=sample_gtin, status=EpcStatus.AVAILABLE))

    db.commit()
