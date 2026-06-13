from __future__ import annotations

from pathlib import Path

from parking_core.models import ParcelFeature
from parking_core.pilot import ParkingRateCompObservation, load_pilot_config
from parking_scoring.engine import score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_load_pilot_merges_baltimore_demand_generators_file() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    names = {g["name"] for g in pilot.scoring.demand_generators}
    assert "Baltimore Penn Station" in names
    assert "Johns Hopkins Hospital — East Baltimore" in names
    assert "Phillips Seafood — Inner Harbor" in names
    assert "Target — Mondawmin" in names
    assert "Seattle downtown retail core" in names
    assert len(pilot.scoring.demand_generators) >= 70


def test_load_pilot_baltimore_profile() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot_baltimore.yaml")
    names = {g["name"] for g in pilot.scoring.demand_generators}
    assert "Whole Foods — Harbor East" in names
    assert len(pilot.scoring.demand_generators) >= 70
    assert pilot.scoring.demand_generator_buffer_m == 450


def test_global_screening_floors_are_candidate_selective() -> None:
    ident = load_pilot_config(REPO_ROOT / "config" / "pilot_identification.yaml")
    strategic = load_pilot_config(REPO_ROOT / "config" / "pilot_strategic.yaml")

    assert ident.scoring.qualified_min_score == 60
    assert strategic.scoring.qualified_min_score == 65
    assert "24510" in ident.region.county_fips
    assert "24510" in strategic.region.county_fips

    no_zoning = ParcelFeature(
        apn="x",
        county_fips="53033",
        lot_sqft=8000,
        zoning_code="unknown",
        zoning_allows_surface_parking=False,
        is_corner_lot=True,
        distance_to_nearest_demand_m=100,
    )
    ident_score = score_parcel(no_zoning, ident)
    assert ident_score.total_score == 55.0
    assert ident_score.total_score < ident.scoring.qualified_min_score

    conditional = ParcelFeature(
        apn="y",
        county_fips="24510",
        lot_sqft=8000,
        zoning_code="C-2",
        zoning_allows_surface_parking=False,
        zoning_principal_use_symbol="CB",
        is_corner_lot=True,
        distance_to_nearest_demand_m=100,
    )
    conditional_ident = score_parcel(conditional, ident)
    assert conditional_ident.total_score == 67.0
    assert conditional_ident.total_score >= ident.scoring.qualified_min_score

    comps = [
        ParkingRateCompObservation(name="Garage A", lat=39.2904, lon=-76.6122, hourly_mid_usd=11.0),
        ParkingRateCompObservation(name="Surface B", lat=39.2820, lon=-76.5920, hourly_mid_usd=8.5),
    ]
    strategic_score = score_parcel(conditional, strategic, nearby_rate_comps=comps)
    assert strategic_score.total_score == 86.0
    assert strategic_score.total_score >= strategic.scoring.qualified_min_score
