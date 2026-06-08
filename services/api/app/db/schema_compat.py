"""Runtime checks when DB schema lags the SQLAlchemy models (split Alembic branches)."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session, load_only

from app.db.models import Parcel
from app.parcel_scored_list import _mailing_address, _situs_address
from app.schemas import ParcelRead
from app.zoning_entitlement import effective_zoning_code, parcel_zoning_symbol, parcel_zoning_tier


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
    Parcel.raw_properties,
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


def parcel_to_read(db: Session, row: Parcel) -> ParcelRead:
    """Build ``ParcelRead`` without touching ORM attrs for missing DB columns."""
    brief = None
    raw = getattr(row, "raw_properties", None)
    raw_dict = raw if isinstance(raw, dict) else None
    zoning_code = effective_zoning_code(row.zoning_code, raw_dict)
    if column_exists(db, "parcels", "owner_outreach_brief"):
        brief = getattr(row, "owner_outreach_brief", None)
    brief_dict = brief if isinstance(brief, dict) else None
    symbol = parcel_zoning_symbol(
        county_fips=row.county_fips,
        zoning_code=zoning_code,
        raw_properties=raw_dict,
    )
    tier = parcel_zoning_tier(
        county_fips=row.county_fips,
        zoning_code=zoning_code,
        raw_properties=raw_dict,
    )
    return ParcelRead(
        id=row.id,
        apn=row.apn,
        county_fips=row.county_fips,
        situs_address=_situs_address(raw_dict, brief_dict),
        mailing_address=_mailing_address(raw_dict, brief_dict),
        lot_sqft=row.lot_sqft,
        zoning_code=zoning_code,
        zoning_allows_surface_parking=row.zoning_allows_surface_parking,
        zoning_principal_use_symbol=symbol,
        zoning_entitlement_tier=tier,
        is_corner_lot=row.is_corner_lot,
        distance_to_nearest_demand_m=row.distance_to_nearest_demand_m,
        owner_outreach_brief=brief,
        created_at=row.created_at,
    )
