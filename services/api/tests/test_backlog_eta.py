from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.backlog_eta import backlog_eta_summary


def _export_payload() -> dict:
    return {
        "parcel_row_total": 223139,
        "parcels_prescreen_qualified": {"count": 12000},
        "parcels_pipeline_funnel_backlog": {"count": 0},
        "parcels_missing_distance_to_nearest_demand_m": {"count": 0},
        "parcels_missing_poi_commercial_count_400m": {"count": 400},
        "parcels_poi_density_candidates": {"count": 500},
        "parcels_missing_score_identification": {"count": 0},
        "parcels_missing_score_entitlement": {"count": 0},
        "parcels_missing_owner_outreach_brief": {"count": 223139},
        "parcels_baltimore_address_candidates": {"count": 12000},
        "parcels_missing_baltimore_property_address": {"count": 11850},
        "parcels_pending_baltimore_address_backfill": {"count": 11100},
    }


def test_backlog_eta_prioritizes_address_backfill_and_ignores_citywide_poi() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=False, ops_remediation_allow_db_writes=False)
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={
                "checked_at": "2026-06-07T16:00:00+00:00",
                "export_readiness": _export_payload(),
                "priority_counties": {
                    "24510": {
                        "county_fips": "24510",
                        "total": 223139,
                        "missing_demand_m": 0,
                        "missing_poi": 202100,
                        "missing_entitlement_score": 0,
                        "missing_identification_score": 0,
                        "pipeline_funnel_backlog": 0,
                    },
                },
            },
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    assert out["summary"]["active_parking_queue_depth"] == 0
    assert out["summary"]["data_source"] == "ops_remediation_snapshot"
    assert out["summary"]["data_checked_at"] == "2026-06-07T16:00:00+00:00"
    assert "address backfill" in out["summary"]["decision"]
    by_key = {row["key"]: row for row in out["items"]}
    assert by_key["baltimore_property_addresses"]["value"] == "high"
    assert by_key["baltimore_property_addresses"]["label"] == "Candidate street address backfill"
    assert by_key["baltimore_property_addresses"]["backlog_count"] == 11100
    assert by_key["baltimore_property_addresses"]["total_count"] == 12000
    assert "no lookup attempt yet" in by_key["baltimore_property_addresses"]["recommendation"]
    assert by_key["baltimore_property_addresses"]["eta_label"] == "Measure one batch first"
    assert by_key["baltimore_poi_density"]["label"] == "Candidate POI density"
    assert by_key["baltimore_poi_density"]["value"] == "medium"
    assert by_key["baltimore_poi_density"]["backlog_count"] == 0
    assert by_key["baltimore_poi_density"]["eta_label"] == "Done"
    assert "citywide POI coverage is optional" in by_key["baltimore_poi_density"]["recommendation"]
    assert "202,100" in by_key["baltimore_poi_density"]["why"]
    assert by_key["owner_outreach_briefs"]["backlog_count"] == 12000
    assert by_key["owner_outreach_briefs"]["total_count"] == 12000
    assert by_key["owner_outreach_briefs"]["backlog_pct"] == 100.0
    assert "failed-prescreen parcels" in by_key["owner_outreach_briefs"]["recommendation"]


def test_backlog_eta_estimates_poi_when_auto_fix_enabled() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=True, ops_remediation_allow_db_writes=True)
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={
                "export_readiness": _export_payload(),
                "priority_counties": {
                    "24510": {
                        "total": 1000,
                        "missing_poi": 9000,
                        "candidate_missing_poi": 1200,
                    },
                },
            },
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    poi = next(row for row in out["items"] if row["key"] == "baltimore_poi_density")
    assert poi["backlog_count"] == 1200
    assert poi["assumed_units_per_day"] == 1200.0
    assert poi["eta_days"] == 1.0


def test_backlog_eta_uses_exact_prescreen_owner_brief_gap_when_available() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=False, ops_remediation_allow_db_writes=False)
    export = {
        **_export_payload(),
        "parcels_missing_owner_outreach_brief": {"count": 223139},
        "parcels_prescreen_qualified_missing_owner_outreach_brief": {"count": 245, "floor": 60.0},
    }
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={
                "export_readiness": export,
                "priority_counties": {
                    "24510": {
                        "total": 223139,
                        "missing_demand_m": 0,
                        "missing_entitlement_score": 0,
                        "missing_identification_score": 0,
                        "pipeline_funnel_backlog": 0,
                    },
                },
            },
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    brief = next(row for row in out["items"] if row["key"] == "owner_outreach_briefs")
    assert brief["backlog_count"] == 245
    assert brief["total_count"] == 12000
    assert brief["backlog_pct"] == 2.04
