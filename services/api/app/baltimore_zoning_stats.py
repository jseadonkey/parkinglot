"""Baltimore City parcel counts by principal-use parking entitlement tier."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Parcel
from app.zoning_entitlement import parcel_zoning_tier

BALTIMORE_CITY_FIPS = "24510"


def baltimore_zoning_tiers_summary(db: Session) -> dict[str, Any]:
    """Group ingested Baltimore City parcels by Article 32 entitlement tier."""
    rows = db.execute(
        select(Parcel.zoning_code, func.count())
        .where(Parcel.county_fips == BALTIMORE_CITY_FIPS)
        .group_by(Parcel.zoning_code)
    ).all()
    tiers: Counter[str] = Counter()
    zones_by_tier: dict[str, Counter[str]] = {
        "permitted": Counter(),
        "conditional": Counter(),
        "council": Counter(),
        "excluded": Counter(),
        "unknown": Counter(),
    }
    total = 0
    for zoning_code, count in rows:
        n = int(count)
        total += n
        z = str(zoning_code).strip() if zoning_code else ""
        tier = parcel_zoning_tier(county_fips=BALTIMORE_CITY_FIPS, zoning_code=z or None, raw_properties=None)
        tiers[tier] += n
        label = z or "(no zoning)"
        zones_by_tier.setdefault(tier, Counter())[label] += n

    top_permitted = [
        {"zoning_code": z, "parcel_count": c}
        for z, c in zones_by_tier.get("permitted", Counter()).most_common(15)
    ]
    return {
        "county_fips": BALTIMORE_CITY_FIPS,
        "total_parcels": total,
        "tiers": dict(tiers),
        "top_permitted_zones": top_permitted,
        "rules_path": "data/zoning/md/baltimore_city_surface_parking_rules.yaml",
    }
