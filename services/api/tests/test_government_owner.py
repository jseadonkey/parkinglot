"""Government / public-agency owner detection and scoring cap."""

from __future__ import annotations

from pathlib import Path

from parking_core.government_owner import (
    government_owner_from_properties,
    is_government_owner_name,
)
from parking_core.models import OwnerKind, ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_enrichment.pipeline import enrich_from_parcel_row
from parking_scoring.engine import GOVERNMENT_OWNER_SCORE_CAP, score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_detects_city_and_county_owner_names() -> None:
    assert is_government_owner_name("KENT CITY OF")
    assert is_government_owner_name("KING COUNTY-FMD FACILITIES MGMT")
    assert is_government_owner_name("PORT OF SEATTLE")
    assert is_government_owner_name("STATE OF WASHINGTON")
    assert not is_government_owner_name("Hong Kong Market LLC")
    assert not is_government_owner_name("Diablo Holdings LLC")


def test_explicit_owner_government_flag() -> None:
    is_gov, name = government_owner_from_properties(
        {"OWNER_NAME": "Some Trust", "OWNER_GOVERNMENT": True}
    )
    assert is_gov is True
    assert name == "Some Trust"


def test_false_government_flag_does_not_override_name() -> None:
    """Scrapers may stamp OWNER_GOVERNMENT=false; name patterns still win."""
    is_gov, name = government_owner_from_properties(
        {"OWNER_NAME": "KING COUNTY-FMD FACILITIES", "OWNER_GOVERNMENT": False}
    )
    assert is_gov is True
    assert "KING COUNTY" in (name or "")


def test_hyphenated_county_fmd_name() -> None:
    assert is_government_owner_name("KING COUNTY-FMD FACILITIES")



def test_enrichment_marks_public_agency() -> None:
    owners = enrich_from_parcel_row({"OWNER_NAME": "KENT CITY OF"})
    assert owners[0].kind == OwnerKind.public
    assert owners[0].raw.get("government_owned") is True


def test_government_owner_caps_total_score() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    private = ParcelFeature(
        apn="priv",
        county_fips="53033",
        lot_sqft=20_000,
        zoning_allows_surface_parking=True,
        is_corner_lot=True,
        distance_to_nearest_demand_m=100,
        poi_commercial_count_400m=40,
        poi_demand_intensity=55.0,
        poi_heavy_anchor_count=2,
        raw_properties={
            "VALUE_BLDG": "0",
            "VALUE_LAND": "500000",
            "OWNER_NAME": "Hong Kong Market LLC",
        },
    )
    public = ParcelFeature(
        apn="gov",
        county_fips="53033",
        lot_sqft=20_000,
        zoning_allows_surface_parking=True,
        is_corner_lot=True,
        distance_to_nearest_demand_m=100,
        poi_commercial_count_400m=40,
        poi_demand_intensity=55.0,
        poi_heavy_anchor_count=2,
        raw_properties={
            "VALUE_BLDG": "0",
            "VALUE_LAND": "500000",
            "OWNER_NAME": "KENT CITY OF",
            "OWNER_GOVERNMENT": True,
        },
    )
    priv_score = score_parcel(private, pilot)
    gov_score = score_parcel(public, pilot)
    assert priv_score.total_score > GOVERNMENT_OWNER_SCORE_CAP
    assert gov_score.total_score <= GOVERNMENT_OWNER_SCORE_CAP
    assert gov_score.pilot_snapshot.get("government_owned") is True
    assert any("public agency" in n.lower() for n in gov_score.breakdown.notes)
