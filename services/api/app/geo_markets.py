"""Geographic market priorities (Baltimore vs Washington statewide)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


def load_geo_markets(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path or get_settings().geo_markets_config_path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def priority_county_fips(path: str | Path | None = None) -> list[str]:
    raw = load_geo_markets(path)
    primary = raw.get("primary_market") if isinstance(raw.get("primary_market"), dict) else {}
    fips = primary.get("priority_county_fips") or []
    if not isinstance(fips, list):
        return []
    return [str(f).strip() for f in fips if str(f).strip()]


def primary_market_summary(path: str | Path | None = None) -> dict[str, Any]:
    raw = load_geo_markets(path)
    primary = raw.get("primary_market") if isinstance(raw.get("primary_market"), dict) else {}
    return {
        "name": str(primary.get("name") or "Baltimore, Maryland"),
        "state_fips": str(primary.get("state_fips") or "24"),
        "primary_metro_cbsa": (str(primary.get("primary_metro_cbsa") or "").strip() or None),
        "priority_county_fips": priority_county_fips(path),
    }


def wa_rollout_pacing(path: str | Path | None = None) -> dict[str, Any]:
    raw = load_geo_markets(path)
    pacing = raw.get("wa_statewide_rollout") if isinstance(raw.get("wa_statewide_rollout"), dict) else {}
    return {
        "min_days_between_counties": int(pacing.get("min_days_between_counties") or 7),
        "max_auto_pipeline": int(pacing.get("max_auto_pipeline") or 15),
        "max_parking_queue_depth": int(pacing.get("max_parking_queue_depth") or 400),
    }
