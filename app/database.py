from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    if _column_exists(table_name, column_name):
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _ensure_order_status_enum_values() -> None:
    with engine.connect() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                text("SELECT unnest(enum_range(NULL::orderstatus))::text")
            ).fetchall()
        }
    for value in ["PICKING", "ALLOCATED", "VERIFIED", "ASN_SENT"]:
        if value in existing:
            continue
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"ALTER TYPE orderstatus ADD VALUE '{value}'"))


def migrate_schema() -> None:
    _add_column_if_missing("message_audit", "topic", "topic VARCHAR(255)")
    _add_column_if_missing("shipments", "asn_number", "asn_number VARCHAR(64)")
    _add_column_if_missing("shipments", "delivery_date", "delivery_date TIMESTAMP")
    _ensure_order_status_enum_values()


def init_db():
    from app import models, order_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_schema()
