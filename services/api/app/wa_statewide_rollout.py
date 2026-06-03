"""Pick the next WA county to ingest for slow statewide rollout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Parcel
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
