"""Phase B overlay validation before merge (coverage vs DB parcel count)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Parcel
from parking_core.pilot import load_pilot_config
from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict, load_geojson_path


def min_overlay_coverage_pct(db_parcel_count: int) -> float:
    """Tiered minimum overlay feature count as % of county parcels in DB."""
    if db_parcel_count >= 100_000:
        return 20.0
    if db_parcel_count >= 10_000:
        return 10.0
    return 5.0


def count_overlay_mergeable_features(
    overlay_path: Path,
    *,
    county_fips: str,
    pilot_config_path: str,
) -> dict[str, int]:
    """Count overlay rows the merge task would iterate for ``county_fips``."""
    data = load_geojson_path(overlay_path)
    pilot = load_pilot_config(pilot_config_path)
    allowed = set(pilot.region.county_fips or [])

    total_iter = 0
    mergeable = 0
    skipped_region = 0
    for attrs, _geom in iter_parcels_from_geojson_dict(data):
        total_iter += 1
        county = str(attrs.get("county_fips") or "").strip()
        apn = str(attrs.get("apn") or "").strip()
        if allowed and county and county not in allowed:
            skipped_region += 1
            continue
        if apn and county == str(county_fips).strip():
            mergeable += 1

    return {
        "features_iterated": total_iter,
        "mergeable_for_county": mergeable,
        "skipped_wrong_region": skipped_region,
    }


def validate_overlay_for_county_merge(
    db: Session,
    overlay_path: Path | str,
    county_fips: str,
    *,
    pilot_config_path: str,
    min_coverage_pct: float | None = None,
) -> dict[str, Any]:
    """Return validation summary; ``ok`` False blocks merge."""
    path = Path(overlay_path)
    cf = str(county_fips).strip()
    if not path.is_file():
        return {
            "ok": False,
            "reason": "overlay_file_missing",
            "overlay_path": str(path),
            "county_fips": cf,
        }

    db_total = int(
        db.scalar(select(func.count()).select_from(Parcel).where(Parcel.county_fips == cf)) or 0,
    )
    if db_total == 0:
        return {
            "ok": False,
            "reason": "no_parcels_in_db",
            "county_fips": cf,
            "db_parcels": 0,
        }

    counts = count_overlay_mergeable_features(
        path,
        county_fips=cf,
        pilot_config_path=pilot_config_path,
    )
    mergeable = int(counts["mergeable_for_county"])
    required_pct = (
        float(min_coverage_pct)
        if min_coverage_pct is not None
        else min_overlay_coverage_pct(db_total)
    )
    coverage_pct = round(100.0 * mergeable / db_total, 4) if db_total else 0.0

    if mergeable == 0:
        return {
            "ok": False,
            "reason": "overlay_has_no_mergeable_features",
            "county_fips": cf,
            "overlay_path": str(path),
            "db_parcels": db_total,
            "required_min_coverage_pct": required_pct,
            **counts,
        }

    if coverage_pct < required_pct:
        return {
            "ok": False,
            "reason": "overlay_coverage_below_minimum",
            "county_fips": cf,
            "overlay_path": str(path),
            "db_parcels": db_total,
            "mergeable_for_county": mergeable,
            "coverage_pct": coverage_pct,
            "required_min_coverage_pct": required_pct,
            **counts,
        }

    return {
        "ok": True,
        "reason": "ok",
        "county_fips": cf,
        "overlay_path": str(path),
        "db_parcels": db_total,
        "mergeable_for_county": mergeable,
        "coverage_pct": coverage_pct,
        "required_min_coverage_pct": required_pct,
        **counts,
    }
