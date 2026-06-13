"""County FIPS helpers — reads geo_markets.yaml, no API import required."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from parking_crew.env import repo_root

# Subset of app.pilot_scope.COUNTY_DISPLAY_NAMES (Baltimore + WA statewide pilot).
COUNTY_DISPLAY_NAMES: dict[str, str] = {
    "24510": "Baltimore City",
    "24005": "Baltimore County",
    "53033": "King",
    "53053": "Pierce",
    "53061": "Snohomish",
    "53063": "Spokane",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def priority_county_fips() -> list[str]:
    root = repo_root()
    geo = _load_yaml(root / "config" / "geo_markets.yaml")
    primary = geo.get("primary_market") if isinstance(geo.get("primary_market"), dict) else {}
    fips_list = primary.get("priority_county_fips") or []
    if isinstance(fips_list, list) and fips_list:
        return [str(f).strip() for f in fips_list if str(f).strip()]

    pilot = _load_yaml(root / "config" / "pilot.yaml")
    region = pilot.get("region") if isinstance(pilot.get("region"), dict) else {}
    fallback = region.get("county_fips") or ["24510"]
    return [str(f).strip() for f in fallback if str(f).strip()]


def region_name_for_fips(county_fips: str) -> str:
    fips = county_fips.strip()
    name = COUNTY_DISPLAY_NAMES.get(fips, fips)
    if fips.startswith("24"):
        return f"{name}, Maryland"
    if fips.startswith("53"):
        return f"{name} County, Washington"
    return name


def default_audit_inputs(county_fips: str | None = None) -> dict[str, str | int | float]:
    fips = (county_fips or priority_county_fips()[0]).strip()
    return {
        "county_fips": fips,
        "region_name": region_name_for_fips(fips),
        "lookback_hours": 168,
        "qualified_score_threshold": 70,
    }
