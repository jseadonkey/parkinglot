"""Seed verified-ish King County / Puget Sound parking rate benchmarks into Postgres."""

from __future__ import annotations

from dataclasses import dataclass

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ParkingRateComp

SEED_TAG = "seed:king-county-pilot-v1"


@dataclass(frozen=True)
class RateCompSeedRow:
    name: str
    lat: float
    lon: float
    hourly_mid_usd: float
    source_note: str


# Public garage/lot benchmarks (mid hourly USD). Replace with operator-verified rates over time.
KING_COUNTY_PARKING_RATE_COMPS: tuple[RateCompSeedRow, ...] = (
    RateCompSeedRow(
        "Pike Place Garage (Downtown)",
        47.6090,
        -122.3415,
        9.0,
        f"{SEED_TAG}; Pike Place Market area published garage rates ~$6–12/hr (2025)",
    ),
    RateCompSeedRow(
        "Pacific Place Garage",
        47.6124,
        -122.3376,
        15.0,
        f"{SEED_TAG}; Downtown retail garage ~$12–18/hr",
    ),
    RateCompSeedRow(
        "Westlake Center Garage",
        47.6112,
        -122.3370,
        16.0,
        f"{SEED_TAG}; Westlake retail garage ~$14–20/hr",
    ),
    RateCompSeedRow(
        "Rainier Square Garage",
        47.6045,
        -122.3310,
        18.0,
        f"{SEED_TAG}; CBD office tower garage ~$16–22/hr",
    ),
    RateCompSeedRow(
        "Convention Center Garage",
        47.6119,
        -122.3315,
        14.0,
        f"{SEED_TAG}; LCC-adjacent event garage ~$12–16/hr",
    ),
    RateCompSeedRow(
        "601 Union Garage (SLU)",
        47.6212,
        -122.3378,
        12.0,
        f"{SEED_TAG}; South Lake Union office garage ~$10–14/hr",
    ),
    RateCompSeedRow(
        "Capitol Hill Broadway Garage",
        47.6158,
        -122.3210,
        8.0,
        f"{SEED_TAG}; Capitol Hill neighborhood garage ~$6–10/hr",
    ),
    RateCompSeedRow(
        "First Hill Medical District",
        47.6065,
        -122.3205,
        11.0,
        f"{SEED_TAG}; First Hill hospital district ~$9–13/hr",
    ),
    RateCompSeedRow(
        "Belltown 5th & Bell",
        47.6155,
        -122.3475,
        13.0,
        f"{SEED_TAG}; Belltown residential/office ~$10–16/hr",
    ),
    RateCompSeedRow(
        "Pioneer Square Garage",
        47.6018,
        -122.3328,
        10.0,
        f"{SEED_TAG}; Pioneer Square surface/structure ~$8–12/hr",
    ),
    RateCompSeedRow(
        "Queen Anne Counterbalance",
        47.6235,
        -122.3570,
        9.0,
        f"{SEED_TAG}; Queen Anne village ~$7–11/hr",
    ),
    RateCompSeedRow(
        "UW District Garage",
        47.6585,
        -122.3125,
        6.0,
        f"{SEED_TAG}; U-District institutional ~$5–8/hr",
    ),
    RateCompSeedRow(
        "Ballard Locks Area",
        47.6680,
        -122.3845,
        7.0,
        f"{SEED_TAG}; Ballard commercial ~$6–9/hr",
    ),
    RateCompSeedRow(
        "Fremont Center",
        47.6505,
        -122.3502,
        8.0,
        f"{SEED_TAG}; Fremont main street ~$6–10/hr",
    ),
    RateCompSeedRow(
        "Bellevue Downtown Lincoln Square",
        47.6158,
        -122.1955,
        12.0,
        f"{SEED_TAG}; Bellevue CBD ~$10–14/hr",
    ),
    RateCompSeedRow(
        "Bellevue The Bravern",
        47.6150,
        -122.1940,
        10.0,
        f"{SEED_TAG}; Bellevue office/retail ~$8–12/hr",
    ),
    RateCompSeedRow(
        "Georgetown Industrial",
        47.5450,
        -122.3250,
        5.0,
        f"{SEED_TAG}; S Seattle industrial ~$4–7/hr",
    ),
    RateCompSeedRow(
        "Renton Downtown",
        47.4825,
        -122.2170,
        5.0,
        f"{SEED_TAG}; Renton civic core ~$4–6/hr",
    ),
    RateCompSeedRow(
        "Tacoma Downtown",
        47.2525,
        -122.4405,
        6.0,
        f"{SEED_TAG}; Tacoma CBD ~$5–8/hr",
    ),
)

SEED_TAG_BALT = "seed:baltimore-pilot-v1"

# Baltimore City + inner Baltimore County paid parking benchmarks (mid hourly USD).
BALTIMORE_PARKING_RATE_COMPS: tuple[RateCompSeedRow, ...] = (
    RateCompSeedRow(
        "Inner Harbor Garage (Light St)",
        39.2865,
        -76.6055,
        12.0,
        f"{SEED_TAG_BALT}; Inner Harbor structured ~$10–15/hr",
    ),
    RateCompSeedRow(
        "Harbor Park Garage (Camden Yards)",
        39.2835,
        -76.6215,
        11.0,
        f"{SEED_TAG_BALT}; Camden Yards event garage ~$9–14/hr",
    ),
    RateCompSeedRow(
        "Harbor East Garage",
        39.2845,
        -76.5995,
        13.0,
        f"{SEED_TAG_BALT}; Harbor East retail/office ~$11–16/hr",
    ),
    RateCompSeedRow(
        "Fells Point surface lot",
        39.2815,
        -76.5925,
        8.5,
        f"{SEED_TAG_BALT}; Fells Point surface ~$7–10/hr",
    ),
    RateCompSeedRow(
        "Canton waterfront lot",
        39.2785,
        -76.5795,
        7.5,
        f"{SEED_TAG_BALT}; Canton Square area ~$6–9/hr",
    ),
    RateCompSeedRow(
        "Federal Hill surface",
        39.2795,
        -76.6105,
        8.0,
        f"{SEED_TAG_BALT}; Federal Hill neighborhood ~$7–10/hr",
    ),
    RateCompSeedRow(
        "Mount Vernon garage",
        39.2975,
        -76.6155,
        9.0,
        f"{SEED_TAG_BALT}; Mount Vernon cultural district ~$8–11/hr",
    ),
    RateCompSeedRow(
        "Penn Station area lot",
        39.3075,
        -76.6155,
        7.0,
        f"{SEED_TAG_BALT}; Penn Station commuter ~$6–9/hr",
    ),
    RateCompSeedRow(
        "Johns Hopkins Hospital garage",
        39.2975,
        -76.5925,
        10.0,
        f"{SEED_TAG_BALT}; East Baltimore medical ~$8–12/hr",
    ),
    RateCompSeedRow(
        "UMB campus lot",
        39.2895,
        -76.6275,
        9.5,
        f"{SEED_TAG_BALT}; University of Maryland Baltimore ~$8–11/hr",
    ),
    RateCompSeedRow(
        "Hampden retail strip",
        39.3355,
        -76.6305,
        6.5,
        f"{SEED_TAG_BALT}; Hampden/The Avenue ~$5–8/hr",
    ),
    RateCompSeedRow(
        "Downtown West Baltimore garage",
        39.2905,
        -76.6185,
        10.5,
        f"{SEED_TAG_BALT}; CBD west ~$9–12/hr",
    ),
    RateCompSeedRow(
        "Little Italy surface",
        39.2875,
        -76.5985,
        8.0,
        f"{SEED_TAG_BALT}; Little Italy ~$7–10/hr",
    ),
    RateCompSeedRow(
        "Towson Town Center garage",
        39.4015,
        -76.6015,
        8.0,
        f"{SEED_TAG_BALT}; Baltimore County Towson ~$6–10/hr",
    ),
    RateCompSeedRow(
        "BWI daily garage (reference)",
        39.1775,
        -76.6685,
        7.0,
        f"{SEED_TAG_BALT}; BWI airport daily ~$6–9/hr (regional anchor)",
    ),
    RateCompSeedRow(
        "Metropolis-style gateless lot (Hampden illustrative)",
        39.3315,
        -76.6325,
        7.5,
        f"{SEED_TAG_BALT}; Unmanned LPR surface ~$6–9/hr (operator illustrative)",
    ),
)


def seed_baltimore_parking_rate_comps(
    db: Session,
    *,
    replace_existing: bool = False,
) -> dict[str, int | bool]:
    """Insert Baltimore metro pilot comps. Skips names already present unless ``replace_existing``."""
    return _seed_rate_comp_rows(
        db,
        BALTIMORE_PARKING_RATE_COMPS,
        replace_existing=replace_existing,
    )


def _existing_by_name(db: Session) -> dict[str, ParkingRateComp]:
    try:
        rows = db.scalars(select(ParkingRateComp).where(ParkingRateComp.active.is_(True))).all()
    except Exception as exc:
        msg = str(exc).lower()
        if "parking_rate_comps" in msg and ("does not exist" in msg or "undefinedtable" in msg):
            return {}
        raise
    return {r.name: r for r in rows}


def _seed_rate_comp_rows(
    db: Session,
    rows: tuple[RateCompSeedRow, ...],
    *,
    replace_existing: bool = False,
) -> dict[str, int | bool]:
    """Insert rate comp rows. Skips names already present unless ``replace_existing``."""
    existing = _existing_by_name(db)
    inserted = 0
    updated = 0
    skipped = 0

    for row in rows:
        prior = existing.get(row.name)
        if prior is not None and not replace_existing:
            skipped += 1
            continue
        location = WKTElement(f"POINT({row.lon} {row.lat})", srid=4326)
        if prior is not None and replace_existing:
            prior.hourly_mid_usd = row.hourly_mid_usd
            prior.source_note = row.source_note
            prior.location = location
            prior.active = True
            updated += 1
            continue
        db.add(
            ParkingRateComp(
                name=row.name,
                hourly_mid_usd=row.hourly_mid_usd,
                source_note=row.source_note,
                location=location,
                active=True,
            ),
        )
        inserted += 1

    db.commit()
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total_seed_rows": len(rows),
        "replace_existing": replace_existing,
    }


def seed_king_county_parking_rate_comps(
    db: Session,
    *,
    replace_existing: bool = False,
) -> dict[str, int | bool]:
    """Insert King County pilot comps. Skips names already present unless ``replace_existing``."""
    return _seed_rate_comp_rows(
        db,
        KING_COUNTY_PARKING_RATE_COMPS,
        replace_existing=replace_existing,
    )
