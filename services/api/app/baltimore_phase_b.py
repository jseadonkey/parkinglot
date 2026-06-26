"""Baltimore City Phase B (zoning overlay merge) helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.wa_phase_b_rollout import county_missing_zoning_stats

BALTIMORE_CITY_FIPS = "24510"
DEFAULT_BALTIMORE_OVERLAY_PATH = "/app/data/baltimore/baltimore_city_zoning_overlay.geojson"
DEFAULT_PIERCE_TRIGGER_FIPS = "53053"


def baltimore_overlay_path(settings: Settings) -> Path:
    raw = (settings.baltimore_phase_b_overlay_path or DEFAULT_BALTIMORE_OVERLAY_PATH).strip()
    return Path(raw)


def baltimore_needs_phase_b_merge(
    db: Session,
    *,
    min_missing_pct: float = 1.0,
) -> tuple[bool, dict[str, Any]]:
    stats = county_missing_zoning_stats(db, BALTIMORE_CITY_FIPS)
    total = stats["total"]
    missing = stats["missing_zoning"]
    if total <= 0:
        return False, {**stats, "missing_pct": None, "reason": "no_parcels"}
    missing_pct = 100.0 * float(missing) / float(total)
    if missing_pct < min_missing_pct:
        return False, {**stats, "missing_pct": missing_pct, "reason": "zoning_mostly_present"}
    return True, {**stats, "missing_pct": missing_pct, "reason": "ready"}


def should_enqueue_baltimore_after_wa_county(settings: Settings, county_fips: str) -> tuple[bool, str]:
    if not settings.baltimore_phase_b_after_pierce_enabled:
        return False, "baltimore_after_pierce_disabled"
    trigger = (settings.baltimore_phase_b_after_pierce_trigger_fips or DEFAULT_PIERCE_TRIGGER_FIPS).strip()
    if str(county_fips).strip() != trigger:
        return False, "not_trigger_county"
    overlay = baltimore_overlay_path(settings)
    if not overlay.is_file():
        return False, "baltimore_overlay_missing"
    return True, "ready"
