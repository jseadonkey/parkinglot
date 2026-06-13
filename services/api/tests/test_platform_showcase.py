from unittest.mock import MagicMock, patch

from app.platform_showcase import build_platform_showcase


def test_build_platform_showcase_shape():
    db = MagicMock()
    db.get.return_value = None

    scoring = {
        "total_parcels": 100,
        "qualified_count_entitlement": 10,
        "parcels_with_both_profiles_scored": 8,
        "qualified_min_score": {"entitlement": 70.0, "strategic": 65.0, "identification": 60.0},
    }
    scope = {
        "region_name": "Baltimore MD (priority) + Washington statewide",
        "state_name": "Maryland + Washington",
        "states_in_scope": [
            {"state_fips": "24", "state_name": "Maryland", "county_count": 2},
            {"state_fips": "53", "state_name": "Washington", "county_count": 39},
        ],
        "primary_market_name": "Baltimore, Maryland",
        "primary_market_state_fips": "24",
        "priority_county_fips": ["24510", "24005"],
        "parcels_in_priority_counties": 0,
        "primary_metro_label": "Seattle",
        "pilot_county_count": 41,
        "counties_with_ingested_parcels": 1,
        "counties": [
            {
                "county_fips": "53033",
                "county_name": "King County",
                "parcels_in_db": 100,
                "priority_market": False,
            },
        ],
    }
    export = {
        "parcel_row_total": 100,
        "parcels_missing_owner_outreach_brief": {"count": 2, "target_count": 5},
        "parcels_prescreen_qualified": {"count": 50},
        "parcels_pipeline_funnel_backlog": {"count": 5},
    }
    dp_summary = MagicMock(total_parcels=3, by_status={"completed": 2}, by_step={"enrich": 1})

    with (
        patch("app.platform_showcase.scoring_summary_stats", return_value=scoring),
        patch("app.platform_showcase.pilot_scope_summary", return_value=scope),
        patch("app.platform_showcase.export_readiness_summary", return_value=export),
        patch("app.platform_showcase.query_deal_progress_board", return_value=(dp_summary, [])),
        patch("app.platform_showcase.query_parcels_scored_list", return_value=[]),
        patch("app.platform_showcase.build_platform_sample_deliverables", return_value=[]),
    ):
        out = build_platform_showcase(db)

    assert out["parcels_total"] == 100
    assert out["parcels_with_owner_brief"] == 3
    assert out["parcels_qualified_entitlement"] == 10
    assert len(out["counties_loaded"]) == 1
