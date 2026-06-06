from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.backlog_eta import backlog_eta_summary


def _export_payload() -> dict:
    return {
        "parcel_row_total": 223139,
        "parcels_pipeline_funnel_backlog": {"count": 0},
        "parcels_missing_distance_to_nearest_demand_m": {"count": 0},
        "parcels_missing_score_identification": {"count": 0},
        "parcels_missing_score_entitlement": {"count": 0},
        "parcels_missing_owner_outreach_brief": {"count": 223139},
    }


def test_backlog_eta_prioritizes_address_backfill_and_throttles_poi() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=False, ops_remediation_allow_db_writes=False)
    with (
        patch("app.backlog_eta.export_readiness_summary", return_value=_export_payload()),
        patch(
            "app.backlog_eta.county_data_gaps",
            return_value={
                "county_fips": "24510",
                "total": 223139,
                "missing_demand_m": 0,
                "missing_poi": 202100,
                "missing_entitlement_score": 0,
                "missing_identification_score": 0,
                "pipeline_funnel_backlog": 0,
            },
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.count_baltimore_missing_property_address", return_value=(223139, 223139)),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=55.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    assert out["summary"]["active_parking_queue_depth"] == 0
    assert "address backfill" in out["summary"]["decision"]
    by_key = {row["key"]: row for row in out["items"]}
    assert by_key["baltimore_property_addresses"]["value"] == "high"
    assert by_key["baltimore_property_addresses"]["eta_label"] == "Measure one batch first"
    assert by_key["baltimore_poi_density"]["value"] == "medium"
    assert by_key["baltimore_poi_density"]["eta_label"] == "Measure one batch first"
    assert "narrow" in by_key["baltimore_poi_density"]["recommendation"].lower()


def test_backlog_eta_estimates_poi_when_auto_fix_enabled() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=True, ops_remediation_allow_db_writes=True)
    with (
        patch("app.backlog_eta.export_readiness_summary", return_value=_export_payload()),
        patch("app.backlog_eta.county_data_gaps", return_value={"total": 1000, "missing_poi": 1200}),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.count_baltimore_missing_property_address", return_value=(0, 1000)),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=55.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    poi = next(row for row in out["items"] if row["key"] == "baltimore_poi_density")
    assert poi["assumed_units_per_day"] == 1200.0
    assert poi["eta_days"] == 1.0
