"""Vacancy / suitability detection from assessor value fields + scoring credit."""

from __future__ import annotations

from pathlib import Path

from parking_core.models import ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_core.suitability import compute_parcel_suitability, suitability_category
from parking_scoring.engine import score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_existing_parking_wa_dor_46() -> None:
    s = compute_parcel_suitability(
        {"LANDUSE_CD": "46", "VALUE_BLDG": "0", "VALUE_LAND": "500000"}
    )
    assert s["is_existing_parking"] is True
    assert s["suitability"] == "existing_parking"
    assert s["is_vacant_land"] is False


def test_vacant_when_building_value_zero_and_land_positive() -> None:
    s = compute_parcel_suitability({"VALUE_BLDG": "0", "VALUE_LAND": "125000"})
    assert s["is_vacant_land"] is True
    assert s["suitability"] == "vacant"
    assert s["improvement_ratio"] == 0.0


def test_existing_parking_king_present_use_180() -> None:
    s = compute_parcel_suitability({"ORIG_LANDUSE_CD": "33-180", "VALUE_BLDG": "0", "VALUE_LAND": "200000"})
    assert s["suitability"] == "existing_parking"


def test_existing_parking_king_landuse_cd_direct() -> None:
    # King WaTech often puts Present Use in LANDUSE_CD (not DOR 46).
    s = compute_parcel_suitability({"LANDUSE_CD": "180", "VALUE_BLDG": "0", "VALUE_LAND": "400000"})
    assert s["suitability"] == "existing_parking"


def test_existing_parking_text_token() -> None:
    s = compute_parcel_suitability({"LANDUSE": "Commercial Parking Lot"})
    assert s["suitability"] == "existing_parking"


def test_vacant_not_parking_when_dor_not_46() -> None:
    s = compute_parcel_suitability({"LANDUSE_CD": "91", "VALUE_BLDG": "0", "VALUE_LAND": "125000"})
    # Numeric 91 alone is not a vacant text token; value heuristic still marks vacant.
    assert s["suitability"] == "vacant"
    assert s["is_existing_parking"] is False


def test_row_utility_not_vacant_even_with_zero_building() -> None:
    # King Present Use 332 = Right Of Way / Utility / Road.
    s = compute_parcel_suitability({"LANDUSE_CD": "332", "VALUE_BLDG": "0", "VALUE_LAND": "3186300"})
    assert s["suitability"] == "unknown"
    assert s["is_vacant_land"] is False


def test_governmental_zero_building_not_vacant() -> None:
    # King 172 = Governmental Service — not a bare lot just because VALUE_BLDG is $0.
    s = compute_parcel_suitability({"LANDUSE_CD": "172", "VALUE_BLDG": "0", "VALUE_LAND": "2000000"})
    assert s["is_vacant_land"] is False
    assert s["suitability"] == "improved"


def test_vacant_commercial_king_309_still_vacant() -> None:
    s = compute_parcel_suitability({"LANDUSE_CD": "309", "VALUE_BLDG": "0", "VALUE_LAND": "1040300"})
    assert s["suitability"] == "vacant"
    assert s["is_vacant_land"] is True


def test_vacant_when_land_use_text_says_vacant() -> None:
    s = compute_parcel_suitability({"LANDUSE_CD": "VACANT COMMERCIAL"})
    assert s["is_vacant_land"] is True
    assert s["suitability"] == "vacant"


def test_baltimore_vacind_is_not_vacant_land() -> None:
    """VACIND marks vacant buildings (often with dwelling units), not bare lots."""
    s = compute_parcel_suitability(
        {"VACIND": "Y", "DWELUNIT": "1", "USEGROUP": "R ", "OWNER_NAME": "Example LLC"}
    )
    assert s["suitability"] != "vacant"
    assert s["is_vacant_land"] is False


def test_baltimore_no_imprv_is_vacant() -> None:
    s = compute_parcel_suitability({"NO_IMPRV": "Y", "USEGROUP": "C "})
    assert s["suitability"] == "vacant"


def test_slucm_undeveloped_91_is_vacant() -> None:
    # SLUCM 91 = Undeveloped Land — genuine bare lot even with $0 building.
    s = compute_parcel_suitability({"LANDUSE_CD": "91", "VALUE_BLDG": "0", "VALUE_LAND": "150000"})
    assert s["is_vacant_land"] is True
    assert s["suitability"] == "vacant"


def test_slucm_developed_use_zero_building_not_vacant() -> None:
    # SLUCM 53 (trade) / 65 (services) with $0 building = tax-exempt / unassessed
    # public site, not an available bare pad.
    for code in ("53", "65", "46", "71"):
        s = compute_parcel_suitability(
            {"LANDUSE_CD": code, "VALUE_BLDG": "0", "VALUE_LAND": "500000"}
        )
        assert s["is_vacant_land"] is False, code
        assert s["suitability"] != "vacant", code


def test_non_slucm_county_code_falls_through_to_value() -> None:
    # Clark's 3-digit 702 is not SLUCM; assessor stays permissive and the aerial
    # rooftop detector is relied on to catch built parcels.
    s = compute_parcel_suitability({"LANDUSE_CD": "702", "VALUE_BLDG": "0", "VALUE_LAND": "2200000"})
    assert s["suitability"] == "vacant"


def test_underutilized_low_improvement_ratio() -> None:
    # $10k building on $190k land → ratio 0.05 → teardown candidate.
    s = compute_parcel_suitability({"VALUE_BLDG": "10000", "VALUE_LAND": "190000"})
    assert s["is_vacant_land"] is False
    assert s["suitability"] == "underutilized"
    assert s["improvement_ratio"] is not None and s["improvement_ratio"] < 0.15


def test_improved_when_meaningful_structure() -> None:
    s = compute_parcel_suitability({"VALUE_BLDG": "400000", "VALUE_LAND": "150000"})
    assert s["suitability"] == "improved"
    assert s["is_vacant_land"] is False


def test_unknown_when_no_value_fields() -> None:
    assert suitability_category({}) == "unknown"
    assert suitability_category(None) == "unknown"
    # A zero building value with no land value is not enough to call it vacant.
    assert suitability_category({"VALUE_BLDG": "0"}) == "unknown"


def test_currency_formatting_is_parsed() -> None:
    s = compute_parcel_suitability({"VALUE_BLDG": "$0", "VALUE_LAND": "$1,250,000"})
    assert s["suitability"] == "vacant"
    assert s["land_value"] == 1250000.0


def test_vacant_land_earns_suitability_score_credit() -> None:
    """A vacant, large, near-demand lot clears the identification floor without zoning."""
    ident = load_pilot_config(REPO_ROOT / "config" / "pilot_identification.yaml")
    vacant_lot = ParcelFeature(
        apn="vac-1",
        county_fips="53033",
        lot_sqft=12000,
        zoning_code="unknown",
        zoning_allows_surface_parking=False,
        is_corner_lot=False,
        distance_to_nearest_demand_m=100,
        raw_properties={"VALUE_BLDG": "0", "VALUE_LAND": "300000"},
    )
    result = score_parcel(vacant_lot, ident)
    # lot 25 + demand 20 + vacant 15 = 60 (>= qualified floor 60), no zoning credit.
    assert result.breakdown.suitability_component == 15.0
    assert result.total_score == 60.0
    assert result.total_score >= ident.scoring.qualified_min_score


def test_improved_lot_earns_no_suitability_credit() -> None:
    ident = load_pilot_config(REPO_ROOT / "config" / "pilot_identification.yaml")
    improved = ParcelFeature(
        apn="imp-1",
        county_fips="53033",
        lot_sqft=12000,
        zoning_code="unknown",
        zoning_allows_surface_parking=False,
        is_corner_lot=False,
        distance_to_nearest_demand_m=100,
        raw_properties={"VALUE_BLDG": "500000", "VALUE_LAND": "300000"},
    )
    result = score_parcel(improved, ident)
    assert result.breakdown.suitability_component == 0.0
    # lot 25 + demand 20 = 45, below the 60 floor — correctly not queued.
    assert result.total_score == 45.0
    assert result.total_score < ident.scoring.qualified_min_score
