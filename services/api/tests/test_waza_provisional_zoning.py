"""WAZA provisional zoning (COM/MXU/IND) for statewide prospect ranking."""

from __future__ import annotations

from pathlib import Path

from app.zoning_entitlement import parcel_zoning_symbol, parcel_zoning_tier
from parking_core.models import ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_core.waza_provisional import provisional_symbol_from_raw
from parking_scoring.engine import score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_provisional_symbol_from_waza_com() -> None:
    assert provisional_symbol_from_raw({"WAZAZoneGeneral": "COM"}) == "PV"
    assert provisional_symbol_from_raw({"WAZAZoneGeneral": "mxu"}) == "PV"
    assert provisional_symbol_from_raw({"WAZAZoneGeneral": "IND"}) == "PV"
    assert provisional_symbol_from_raw({"WAZAZoneGeneral": "LIR"}) is None
    assert provisional_symbol_from_raw({}) is None


def test_parcel_symbol_uses_waza_when_no_curated_rules() -> None:
    sym = parcel_zoning_symbol(
        county_fips="53021",
        zoning_code="C-3",
        raw_properties={
            "ZONING_JURISDICTION": "pasco_city",
            "WAZAZoneGeneral": "COM",
        },
    )
    assert sym == "PV"
    assert (
        parcel_zoning_tier(
            county_fips="53021",
            zoning_code="C-3",
            raw_properties={
                "ZONING_JURISDICTION": "pasco_city",
                "WAZAZoneGeneral": "COM",
            },
        )
        == "provisional"
    )


def test_provisional_gets_conditional_score_credit() -> None:
    ident = load_pilot_config(REPO_ROOT / "config" / "pilot_identification.yaml")
    feat = ParcelFeature(
        apn="waza-1",
        county_fips="53021",
        lot_sqft=12000,
        zoning_code="C-3",
        zoning_allows_surface_parking=False,
        zoning_principal_use_symbol="PV",
        is_corner_lot=False,
        distance_to_nearest_demand_m=200,
        raw_properties={
            "VALUE_BLDG": "0",
            "VALUE_LAND": "200000",
            "WAZAZoneGeneral": "COM",
        },
    )
    result = score_parcel(feat, ident)
    # lot 25 + demand 20 + vacant 15 + PV conditional 15 = 75
    assert result.breakdown.zoning_component == 15.0
    assert result.breakdown.suitability_component == 15.0
    assert result.breakdown.demand_proximity_component == 20.0
    assert result.total_score >= ident.scoring.qualified_min_score
    assert any("provisional" in n.lower() or "WAZA" in n for n in result.breakdown.notes)


def test_poi_density_can_earn_demand_credit() -> None:
    ident = load_pilot_config(REPO_ROOT / "config" / "pilot_identification.yaml")
    feat = ParcelFeature(
        apn="poi-1",
        county_fips="53063",
        lot_sqft=12000,
        zoning_allows_surface_parking=False,
        is_corner_lot=False,
        distance_to_nearest_demand_m=50_000,
        poi_commercial_count_400m=8,
        raw_properties={"VALUE_BLDG": "0", "VALUE_LAND": "100000"},
    )
    result = score_parcel(feat, ident)
    assert result.breakdown.demand_proximity_component == 20.0
