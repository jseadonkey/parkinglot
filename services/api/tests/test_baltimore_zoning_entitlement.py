"""Tests for Baltimore Article 32 principal-use parking symbols and scoring."""

from __future__ import annotations

from pathlib import Path

from parking_core.models import ParcelFeature
from parking_core.pilot import PilotConfig, ScoringConfig, ScoringWeights
from parking_ingestion.zoning_rules import (
    load_effective_zoning_rules,
    resolve_principal_use_symbol,
    zone_codes_for_tier,
    zoning_entitlement_tier,
)
from parking_scoring.engine import score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_baltimore_c3_is_permitted_symbol() -> None:
    rules = load_effective_zoning_rules(REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml")
    assert resolve_principal_use_symbol("C-3", "baltimore_city", rules) == "P"
    assert zoning_entitlement_tier("P") == "permitted"


def test_baltimore_c5_base_is_council_not_permitted() -> None:
    rules = load_effective_zoning_rules(REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml")
    assert resolve_principal_use_symbol("C-5", "baltimore_city", rules) == "CO"
    assert zoning_entitlement_tier("CO") == "council"


def test_baltimore_compact_downtown_aliases_are_not_unknown() -> None:
    rules = load_effective_zoning_rules(REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml")
    for code in ("DCE", "C-5DC", "C5DC*", "C-5DE", "C-5IH", "C-5HT"):
        assert resolve_principal_use_symbol(code, "baltimore_city", rules) == "CB"
        assert zoning_entitlement_tier(resolve_principal_use_symbol(code, "baltimore_city", rules)) == "conditional"


def test_baltimore_compact_permitted_aliases() -> None:
    rules = load_effective_zoning_rules(REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml")
    for code in ("C-5TO", "C5TO*", "C-5HS"):
        assert resolve_principal_use_symbol(code, "baltimore_city", rules) == "P"
        assert zoning_entitlement_tier(resolve_principal_use_symbol(code, "baltimore_city", rules)) == "permitted"


def test_baltimore_cb_gets_partial_zoning_credit() -> None:
    pilot = PilotConfig(
        region={"name": "t", "state_fips": "24", "county_fips": ["24510"]},
        deal={"primary_structure": "ground_lease", "allowed_structures": ["ground_lease"]},
        compliance={"allowed_outreach_channels": [], "require_human_approval_for": []},
        scoring=ScoringConfig(
            min_lot_sqft=5000,
            weights=ScoringWeights(
                zoning_permitted_surface_parking=35,
                zoning_conditional_surface_parking=12,
                lot_size=18,
                corner_lot=8,
                near_demand_generator_m=24,
            ),
        ),
    )
    feat = ParcelFeature(
        apn="x",
        county_fips="24510",
        lot_sqft=8000,
        zoning_code="C-1",
        zoning_allows_surface_parking=False,
        zoning_principal_use_symbol="CB",
        distance_to_nearest_demand_m=100,
    )
    result = score_parcel(feat, pilot)
    assert result.breakdown.zoning_component == 12.0
    assert any("BMZA conditional" in n for n in result.breakdown.notes)


def test_permitted_zone_code_filter_non_empty() -> None:
    rules = load_effective_zoning_rules(REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml")
    codes = zone_codes_for_tier("baltimore_city", "permitted", rules)
    assert "C-3" in codes
    assert "I-1" in codes
    assert "C-5" not in codes
