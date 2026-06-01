"""Runtime checks when DB schema lags the SQLAlchemy models (split Alembic branches)."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session, load_only

from app.db.models import Parcel


def table_exists(db: Session, name: str) -> bool:
    try:
        return name in inspect(db.get_bind()).get_table_names()
    except Exception:
        return False


def column_exists(db: Session, table: str, column: str) -> bool:
    try:
        cols = inspect(db.get_bind()).get_columns(table)
    except Exception:
        return False
    return any(c.get("name") == column for c in cols)


_PARCEL_BASE = (
    Parcel.id,
    Parcel.apn,
    Parcel.county_fips,
    Parcel.lot_sqft,
    Parcel.zoning_code,
    Parcel.zoning_allows_surface_parking,
    Parcel.is_corner_lot,
    Parcel.distance_to_nearest_demand_m,
    Parcel.created_at,
)


def parcel_load_only(db: Session):
    """Omit ORM columns that are not present in Postgres yet."""
    attrs: list = list(_PARCEL_BASE)
    if column_exists(db, "parcels", "owner_outreach_brief"):
        attrs.append(Parcel.owner_outreach_brief)
    return load_only(*attrs)
