"""Tests for Baltimore zoning tier helpers and entitlement rescore."""

from __future__ import annotations

from pathlib import Path

from parking_core.models import ParcelFeature
from parking_core.pilot import PilotConfig, ScoringConfig, ScoringWeights
from parking_ingestion.zoning_rules import load_effective_zoning_rules, zone_codes_for_tier
from parking_scoring.engine import score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_permitted_zone_codes_include_industrial_and_commercial() -> None:
    rules = load_effective_zoning_rules(REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml")
    permitted = zone_codes_for_tier("baltimore_city", "permitted", rules)
    conditional = zone_codes_for_tier("baltimore_city", "conditional", rules)
    assert "I-1" in permitted
    assert "C-3" in permitted
    assert "C-5" not in permitted
    assert "C-1" in conditional
    assert "C-5-DC" in conditional


def test_entitlement_merge_scoring_cb_partial() -> None:
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
            ),
        ),
    )
    feat = ParcelFeature(
        apn="x",
        county_fips="24510",
        lot_sqft=8000,
        zoning_code="I-1",
        zoning_allows_surface_parking=True,
        zoning_principal_use_symbol="P",
        distance_to_nearest_demand_m=100,
    )
    assert score_parcel(feat, pilot).breakdown.zoning_component == 35.0

    cb = feat.model_copy(
        update={
            "zoning_code": "C-1",
            "zoning_allows_surface_parking": False,
            "zoning_principal_use_symbol": "CB",
        }
    )
    assert score_parcel(cb, pilot).breakdown.zoning_component == 12.0
