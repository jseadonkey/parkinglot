"""End-to-end trace for bundled Washington sample GeoJSON (scores, enrichment, memo).

Keeps manual walkthrough steps in sync with CI: `make verify-sample` or pytest this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parking_core.models import ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_enrichment.owner_outreach_agent import build_owner_outreach_brief
from parking_enrichment.pipeline import enrich_from_parcel_row
from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict, load_geojson_path
from parking_scoring.engine import score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_GEOJSON = REPO_ROOT / "data" / "sample_parcels.geojson"
PILOT_YAML = REPO_ROOT / "config" / "pilot.yaml"


@pytest.fixture
def pilot():
    assert PILOT_YAML.is_file(), f"missing {PILOT_YAML}"
    return load_pilot_config(PILOT_YAML)


@pytest.fixture
def sample_data() -> dict:
    assert SAMPLE_GEOJSON.is_file(), f"missing {SAMPLE_GEOJSON}"
    return json.loads(SAMPLE_GEOJSON.read_text())


def test_sample_geojson_scores_and_qualification(pilot) -> None:
    """Loader → ParcelFeature → score_parcel matches expected totals for sample fixtures."""
    data = load_geojson_path(SAMPLE_GEOJSON)
    by_apn: dict[str, float] = {}
    qualified: dict[str, bool] = {}
    floor = float(pilot.scoring.qualified_min_score)

    for attrs, _geom in iter_parcels_from_geojson_dict(data):
        apn = attrs["apn"]
        feat = ParcelFeature(
            apn=attrs["apn"],
            county_fips=str(attrs["county_fips"] or ""),
            lot_sqft=attrs.get("lot_sqft"),
            zoning_code=str(attrs["zoning_code"]) if attrs.get("zoning_code") else None,
            zoning_allows_surface_parking=bool(attrs.get("zoning_allows_surface_parking")),
            is_corner_lot=bool(attrs.get("is_corner_lot")),
            distance_to_nearest_demand_m=float(attrs["distance_to_nearest_demand_m"])
            if attrs.get("distance_to_nearest_demand_m") is not None
            else None,
        )
        result = score_parcel(feat, pilot)
        by_apn[apn] = result.total_score
        qualified[apn] = result.total_score >= floor

    assert by_apn["WA-KING-SAMPLE-001"] == 100.0
    assert qualified["WA-KING-SAMPLE-001"] is True
    assert by_apn["WA-KING-SAMPLE-002"] == 0.0
    assert qualified["WA-KING-SAMPLE-002"] is False


def test_sample_enrichment_and_outreach_brief(sample_data: dict) -> None:
    """Assessor-style OWNER_NAME drives entity vs individual and WA SOS path."""
    feats = sample_data["features"]
    assert len(feats) >= 2

    # Entity LLC in King County → SOS + vendor steps
    p1 = feats[0]["properties"]
    owners1 = enrich_from_parcel_row(p1)
    assert owners1[0].display_name == "Puget Sound Example Holdings LLC"
    assert owners1[0].kind.value == "entity"
    brief1 = build_owner_outreach_brief(
        county_fips=p1["COUNTY_FIPS"],
        apn=p1["APN"],
        raw_properties=p1,
        owners=owners1,
    )
    channels = [s.channel.value for s in brief1.steps]
    assert "secretary_of_state" in channels
    assert "vendor_research" in channels
    assert any("mailing address" in g.lower() for g in brief1.data_gaps)

    # Individual → no SOS entity path; still vendor fallback
    p2 = feats[1]["properties"]
    owners2 = enrich_from_parcel_row(p2)
    assert owners2[0].kind.value == "individual"
    brief2 = build_owner_outreach_brief(
        county_fips=p2["COUNTY_FIPS"],
        apn=p2["APN"],
        raw_properties=p2,
        owners=owners2,
    )
    assert [s.channel.value for s in brief2.steps] == ["vendor_research"]


def test_deal_memo_includes_outreach_brief_section(pilot) -> None:
    """Pipeline passes outreach_brief into memo render; body must list steps."""
    from app.memo_render import build_deal_memo_markdown

    props = {
        "APN": "WA-KING-SAMPLE-001",
        "COUNTY_FIPS": "53033",
        "OWNER_NAME": "Puget Sound Example Holdings LLC",
    }
    owners = enrich_from_parcel_row(props)
    brief = build_owner_outreach_brief(
        county_fips="53033",
        apn="WA-KING-SAMPLE-001",
        raw_properties=props,
        owners=owners,
    )
    feat = ParcelFeature(
        apn="WA-KING-SAMPLE-001",
        county_fips="53033",
        lot_sqft=14000.0,
        zoning_code="Downtown Commercial (example)",
        zoning_allows_surface_parking=True,
        is_corner_lot=True,
        distance_to_nearest_demand_m=180.0,
    )
    score = score_parcel(feat, pilot)
    owner_lines = [f"{o.display_name} ({o.kind}, conf={o.confidence:.2f}, {o.source})" for o in owners]
    title, body, _oq = build_deal_memo_markdown(
        apn="WA-KING-SAMPLE-001",
        county_fips="53033",
        zoning_code="Downtown Commercial (example)",
        lot_sqft=14000.0,
        score=score,
        owner_lines=owner_lines,
        outreach_brief=brief,
    )
    assert "Deal memo" in title
    assert "Owner outreach brief (deterministic rules)" in body
    assert "Washington Secretary of State" in body
