from unittest.mock import MagicMock, patch

from app.platform_showcase import build_platform_showcase


def test_build_platform_showcase_shape():
    db = MagicMock()
    db.get.return_value = None

    scoring = {
        "total_parcels": 100,
        "qualified_count_entitlement": 10,
        "parcels_with_both_profiles_scored": 8,
        "qualified_min_score": {"entitlement": 55.0, "strategic": 50.0, "identification": 45.0},
    }
    scope = {
        "region_name": "WA pilot",
        "state_name": "Washington",
        "primary_metro_label": "Seattle",
        "pilot_county_count": 39,
        "counties_with_ingested_parcels": 1,
        "counties": [{"county_fips": "53033", "county_name": "King County", "parcels_in_db": 100}],
    }
    export = {
        "parcel_row_total": 100,
        "parcels_missing_owner_outreach_brief": {"count": 90},
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
    assert out["parcels_with_owner_brief"] == 10
    assert out["parcels_qualified_entitlement"] == 10
    assert len(out["counties_loaded"]) == 1
