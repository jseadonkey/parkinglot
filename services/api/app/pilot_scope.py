"""Pilot geography and scope for operator dashboards."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Parcel
from app.geo_markets import primary_market_summary, priority_county_fips
from parking_core.pilot import load_pilot_config

# ANSI county FIPS → display name (Washington state = 53).
WA_COUNTY_NAMES: dict[str, str] = {
    "53001": "Adams",
    "53003": "Asotin",
    "53005": "Benton",
    "53007": "Chelan",
    "53009": "Clallam",
    "53011": "Clark",
    "53013": "Columbia",
    "53015": "Cowlitz",
    "53017": "Douglas",
    "53019": "Ferry",
    "53021": "Franklin",
    "53023": "Garfield",
    "53025": "Grant",
    "53027": "Grays Harbor",
    "53029": "Island",
    "53031": "Jefferson",
    "53033": "King",
    "53035": "Kitsap",
    "53037": "Kittitas",
    "53039": "Klickitat",
    "53041": "Lewis",
    "53043": "Lincoln",
    "53045": "Mason",
    "53047": "Okanogan",
    "53049": "Pacific",
    "53051": "Pend Oreille",
    "53053": "Pierce",
    "53055": "San Juan",
    "53057": "Skagit",
    "53059": "Skamania",
    "53061": "Snohomish",
    "53063": "Spokane",
    "53065": "Stevens",
    "53067": "Thurston",
    "53069": "Wahkiakum",
    "53071": "Walla Walla",
    "53073": "Whatcom",
    "53075": "Whitman",
    "53077": "Yakima",
}

CBSA_LABELS: dict[str, str] = {
    "42660": "Seattle-Tacoma-Bellevue, WA",
    "12580": "Baltimore-Columbia-Towson, MD",
}

STATE_FIPS_NAMES: dict[str, str] = {
    "53": "Washington",
    "24": "Maryland",
}

MD_COUNTY_NAMES: dict[str, str] = {
    "24510": "Baltimore City",
    "24005": "Baltimore County",
}

COUNTY_DISPLAY_NAMES: dict[str, str] = {**WA_COUNTY_NAMES, **MD_COUNTY_NAMES}


def pilot_scope_summary(db: Session) -> dict[str, Any]:
    """Region config from pilot YAML plus parcel counts per in-scope county."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    pilot_i = load_pilot_config(settings.pilot_identification_config_path)
    pilot_s = load_pilot_config(settings.pilot_strategic_config_path)

    region = pilot.region
    state_fips = (region.state_fips or "").strip()
    pilot_fips = sorted({str(f).strip() for f in (region.county_fips or []) if str(f).strip()})

    counts_by_fips: dict[str, int] = {}
    for fips, cnt in db.execute(
        select(Parcel.county_fips, func.count())
        .where(Parcel.county_fips.in_(pilot_fips))
        .group_by(Parcel.county_fips)
    ):
        counts_by_fips[str(fips)] = int(cnt or 0)

    pri = set(priority_county_fips())
    counties = [
        {
            "county_fips": fips,
            "county_name": COUNTY_DISPLAY_NAMES.get(fips, fips),
            "parcels_in_db": counts_by_fips.get(fips, 0),
            "priority_market": fips in pri,
        }
        for fips in pilot_fips
    ]
    counties_with_data = sum(1 for c in counties if c["parcels_in_db"] > 0)
    total_in_scope = sum(c["parcels_in_db"] for c in counties)

    cbsa = (region.primary_metro_cbsa or "").strip() or None
    primary = primary_market_summary()
    pri_fips = primary["priority_county_fips"]
    parcels_priority = sum(counts_by_fips.get(f, 0) for f in pri_fips)
    return {
        "region_name": region.name,
        "state_fips": state_fips,
        "state_name": STATE_FIPS_NAMES.get(state_fips, state_fips or "Unknown"),
        "primary_market_name": primary["name"],
        "primary_market_state_fips": primary["state_fips"],
        "priority_county_fips": pri_fips,
        "parcels_in_priority_counties": parcels_priority,
        "primary_metro_cbsa": cbsa,
        "primary_metro_label": CBSA_LABELS.get(cbsa or "", cbsa),
        "pilot_county_count": len(pilot_fips),
        "counties_with_ingested_parcels": counties_with_data,
        "parcels_in_pilot_counties": total_in_scope,
        "min_lot_sqft": float(pilot.scoring.min_lot_sqft),
        "qualified_min_score": {
            "entitlement": float(pilot.scoring.qualified_min_score),
            "strategic": float(pilot_s.scoring.qualified_min_score),
            "identification": float(pilot_i.scoring.qualified_min_score),
        },
        "counties": counties,
    }
