from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.candidate_address import (
    count_candidate_pool_parcels,
    count_target_candidate_address_backfill_parcels,
    count_wa_candidate_pool_parcels,
)
from app.db.models import Parcel


def county_parcel_count(db: Session, county_fips: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Parcel)
            .where(Parcel.county_fips == county_fips)
        )
        or 0
    )


def county_candidate_address_coverage(db: Session, county_fips: str) -> dict[str, Any]:
    """Candidate-only situs coverage for one county."""
    total_candidates = count_candidate_pool_parcels(db, county_fips=county_fips)
    gap = count_target_candidate_address_backfill_parcels(db, county_fips=county_fips)
    with_addr = max(0, total_candidates - gap)
    pct = round(100.0 * with_addr / total_candidates, 2) if total_candidates else 0.0
    return {
        "county_fips": county_fips,
        "parcels_loaded": county_parcel_count(db, county_fips),
        "candidate_pool": total_candidates,
        "candidate_with_address": with_addr,
        "candidate_gap": gap,
        "candidate_address_pct": pct,
    }


def baltimore_candidate_coverage(db: Session) -> dict[str, Any]:
    return county_candidate_address_coverage(db, "24510")


def wa_statewide_summary(db: Session) -> dict[str, Any]:
    pool = count_wa_candidate_pool_parcels(db)
    gap = count_target_candidate_address_backfill_parcels(db, wa_only=True)
    with_addr = max(0, pool - gap)
    pct = round(100.0 * with_addr / pool, 2) if pool else 0.0
    return {
        "candidate_pool": pool,
        "candidate_with_address": with_addr,
        "candidate_gap": gap,
        "candidate_address_pct": pct,
    }
