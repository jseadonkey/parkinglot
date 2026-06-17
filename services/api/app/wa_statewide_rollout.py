"""Pick the next WA county to ingest for slow statewide rollout."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Parcel
from parking_core.pilot import load_pilot_config


def load_rollout_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def county_priority_list(config: dict[str, Any], *, pilot_config_path: str) -> list[str]:
    """WA-only counties for WaTech ingest (state FIPS 53 — excludes Baltimore MD)."""
    raw = config.get("county_fips_priority")
    if isinstance(raw, list) and raw:
        fips_list = [str(f).strip() for f in raw if str(f).strip()]
    else:
        pilot = load_pilot_config(pilot_config_path)
        fips_list = sorted(str(f).strip() for f in (pilot.region.county_fips or []) if str(f).strip())
    return [f for f in fips_list if f.startswith("53")]


def parcel_counts_by_county(db: Session, county_fips: list[str]) -> dict[str, int]:
    if not county_fips:
        return {}
    rows = db.execute(
        select(Parcel.county_fips, func.count())
        .where(Parcel.county_fips.in_(county_fips))
        .group_by(Parcel.county_fips),
    )
    return {str(fips): int(cnt or 0) for fips, cnt in rows}


def cooldown_days_after_county(parcels_loaded: int, config: dict[str, Any]) -> float:
    """Days to wait before starting the next county — scales with last county size."""
    if config.get("min_days_per_10k_parcels") is not None or config.get("min_days_base") is not None:
        base = float(config.get("min_days_base") or 0.5)
        per_10k = float(config.get("min_days_per_10k_parcels") or 0.75)
        cap = float(config.get("min_days_max") or 10.0)
        days = base + (max(0, int(parcels_loaded)) / 10_000.0) * per_10k
        return min(cap, max(base, days))
    return float(config.get("min_days_between_counties") or 7)


def merge_rollout_config(rollout: dict[str, Any], pacing: dict[str, Any]) -> dict[str, Any]:
    """``wa_statewide_rollout.yaml`` overrides ``geo_markets.yaml`` pacing defaults."""
    return {**pacing, **rollout}


def wa_rollout_cooldown_state(
    db: Session,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Whether enough time has passed since the last WA county ingest (size-aware)."""
    last = db.execute(
        select(AuditLog)
        .where(AuditLog.action == "wa_statewide_county_ingest")
        .order_by(AuditLog.created_at.desc())
        .limit(1),
    ).scalar_one_or_none()
    if last is None or last.created_at is None:
        return {
            "ready": True,
            "required_cooldown_days": 0.0,
            "days_since_last_ingest": None,
            "last_county_fips": None,
            "last_county_parcels_in_db": 0,
        }

    county = str(last.entity_id or "").strip()
    parcels = 0
    if county:
        parcels = parcel_counts_by_county(db, [county]).get(county, 0)
    required = cooldown_days_after_county(parcels, config)
    created = last.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - created).total_seconds() / 86400.0
    return {
        "ready": age_days >= required,
        "required_cooldown_days": round(required, 2),
        "days_since_last_ingest": round(age_days, 2),
        "last_county_fips": county or None,
        "last_county_parcels_in_db": parcels,
    }


def wa_rollout_pending_ingest_state(db: Session, config: dict[str, Any]) -> dict[str, Any]:
    """Detect a county that has been started but has not landed rows yet."""
    last = db.execute(
        select(AuditLog)
        .where(AuditLog.action == "wa_statewide_county_ingest")
        .order_by(AuditLog.created_at.desc())
        .limit(1),
    ).scalar_one_or_none()
    lock_days = float(config.get("pending_ingest_lock_days") or 0.1)
    if last is None or last.created_at is None:
        return {
            "pending": False,
            "pending_county_fips": None,
            "pending_age_days": None,
            "pending_lock_days": lock_days,
        }

    county = str(last.entity_id or "").strip()
    if not county:
        return {
            "pending": False,
            "pending_county_fips": None,
            "pending_age_days": None,
            "pending_lock_days": lock_days,
        }

    parcels = parcel_counts_by_county(db, [county]).get(county, 0)
    created = last.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - created).total_seconds() / 86400.0
    pending = parcels <= 0 and age_days < lock_days
    return {
        "pending": pending,
        "pending_county_fips": county if pending else None,
        "pending_age_days": round(age_days, 2) if pending else None,
        "pending_lock_days": lock_days,
    }


def parking_queue_depth(redis_url: str) -> int:
    import redis

    client = redis.from_url(redis_url)
    try:
        return int(client.llen("parking") or 0)
    finally:
        client.close()


def next_county_to_ingest(
    db: Session,
    *,
    config: dict[str, Any],
    pilot_config_path: str,
) -> str | None:
    """First priority county with zero parcel rows in DB."""
    priority = county_priority_list(config, pilot_config_path=pilot_config_path)
    counts = parcel_counts_by_county(db, priority)
    for fips in priority:
        if counts.get(fips, 0) == 0:
            return fips
    return None
