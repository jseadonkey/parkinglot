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
    inv = out["inventory"]
    assert inv["records_gathered"] == 223139
    assert inv["records_gathering"] == 0
    assert inv["pipeline_backlog"] == 0
    by_key = {row["key"]: row for row in out["items"]}
    assert by_key["baltimore_property_addresses"]["value"] == "high"
    assert by_key["baltimore_property_addresses"]["label"] == "Candidate street address backfill"
    assert by_key["baltimore_property_addresses"]["backlog_count"] == 0
    assert by_key["baltimore_property_addresses"]["total_count"] == 12000
    assert "stale" in by_key["baltimore_property_addresses"]["recommendation"].lower()
    assert by_key["baltimore_property_addresses"]["eta_label"] == "Done"
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


def test_backlog_eta_uses_scoped_address_gap_when_snapshot_has_it() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=False, ops_remediation_allow_db_writes=False)
    export = {
        **_export_payload(),
        "parcels_missing_baltimore_candidate_street_address": {
            "count": 52,
            "target_count": 5415,
            "pct": 0.96,
            "floor": 45.0,
        },
    }
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={"export_readiness": export, "priority_counties": {}},
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    addr = next(row for row in out["items"] if row["key"] == "baltimore_property_addresses")
    assert addr["backlog_count"] == 52
    assert addr["total_count"] == 5415
    assert "deal candidates only" in addr["recommendation"]


def test_backlog_eta_does_not_count_parcels_when_cached_snapshot_missing() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=False, ops_remediation_allow_db_writes=False)
    db = MagicMock()
    db.scalar.side_effect = AssertionError("backlog ETA must not run live parcel counts")
    with (
        patch("app.backlog_eta.load_last_report", return_value=None),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
    ):
        out = backlog_eta_summary(db, settings)  # type: ignore[arg-type]

    assert out["summary"]["data_source"] == "live_fallback"
    assert len(out["items"]) > 0
    db.scalar.assert_not_called()


def test_backlog_eta_uses_cached_load_governor_without_recompute() -> None:
    settings = SimpleNamespace(
        ops_remediation_auto_fix=False,
        ops_remediation_allow_db_writes=False,
        load_governor_enabled=True,
    )
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={
                "export_readiness": _export_payload(),
                "priority_counties": {"24510": {"total": 1000}},
            },
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}) as queues,
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}) as workers,
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
        patch("app.load_governor.load_governor_state", return_value=None) as load_governor_state,
        patch("app.load_governor.refresh_load_governor") as refresh_load_governor,
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    queues.assert_called_once_with(settings, socket_timeout=1.0)
    workers.assert_called_once_with(timeout=1.0)
    load_governor_state.assert_called_once_with(settings, socket_timeout=1.0)
    refresh_load_governor.assert_not_called()
    assert out["summary"]["load_governor_pressure_level"] == "green"


def test_backlog_eta_does_not_treat_broad_entitlement_gap_as_actionable_score_backlog() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=False, ops_remediation_allow_db_writes=False)
    export = {
        **_export_payload(),
        "parcels_missing_score_identification": {"count": 0},
        "parcels_missing_score_entitlement": {"count": 1000},
        "parcels_pipeline_funnel_backlog": {"count": 0},
    }
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={"export_readiness": export, "priority_counties": {}},
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
        patch("app.site_watchdog.load_last_report", return_value=None),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    score = next(row for row in out["items"] if row["key"] == "score_gaps")
    assert score["label"] == "Actionable score gaps"
    assert score["backlog_count"] == 0
    assert score["recommendation"] == "No action needed."
    assert out["summary"]["score_gaps_total"] == 0
    assert out["server_load"]["gross_entitlement_gaps"] == 1000
    latent = out["server_load"]["latent_gaps"]
    assert any(row["key"] == "broad_entitlement_coverage" for row in latent)
    assert out["server_load"]["pressure_triggers"] == []


def test_backlog_eta_inventory_uses_cached_pilot_scope() -> None:
    settings = SimpleNamespace(ops_remediation_auto_fix=False, ops_remediation_allow_db_writes=False)
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={
                "export_readiness": _export_payload(),
                "priority_counties": {},
                "pilot_scope": {
                    "region_name": "Baltimore MD + Washington statewide",
                    "pilot_county_count": 41,
                    "counties_with_ingested_parcels": 5,
                    "parcels_in_pilot_counties": 223139,
                },
            },
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 12, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    inv = out["inventory"]
    assert inv["records_gathered"] == 223139
    assert inv["records_gathering"] == 12
    assert inv["counties_gathered"] == 5
    assert inv["counties_to_be_gathered"] == 36
    assert inv["pilot_county_count"] == 41
    assert "12 Celery tasks" in inv["gathering_note"]


def test_backlog_eta_inventory_falls_back_to_pilot_yaml_without_scope() -> None:
    settings = SimpleNamespace(
        ops_remediation_auto_fix=False,
        ops_remediation_allow_db_writes=False,
        pilot_config_path="config/pilot.yaml",
    )
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={"export_readiness": _export_payload(), "priority_counties": {}},
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    inv = out["inventory"]
    assert inv["records_gathered"] == 223139
    assert inv["county_breakdown_pending"] is True
    assert inv["pilot_county_count"] >= 2
    assert inv["counties_to_be_gathered"] == inv["pilot_county_count"]


def test_backlog_eta_watchdog_trigger_surfaces_as_pressure_not_latent_gap() -> None:
    settings = SimpleNamespace(
        ops_remediation_auto_fix=False,
        ops_remediation_allow_db_writes=False,
        load_governor_enabled=True,
    )
    export = {
        **_export_payload(),
        "parcels_missing_score_entitlement": {"count": 1_462_340},
    }
    governor = {
        "pressure_level": "orange",
        "assessed_at": "2026-06-12T01:00:00+00:00",
        "score_gaps": 0,
        "score_gap_basis": "identification_plus_pipeline_funnel",
        "gross_entitlement_gaps": 1_462_340,
        "pipeline_enqueue_multiplier": 0.25,
        "wa_rollout_allowed": False,
        "ops_autofix_allowed": False,
        "signals": [{"code": "site_watchdog_failed"}],
        "decision": "High downstream pressure",
    }
    with (
        patch(
            "app.backlog_eta.load_last_report",
            return_value={
                "export_readiness": export,
                "priority_counties": {"24510": {"total": 1000, "missing_poi": 201200}},
            },
        ),
        patch("app.backlog_eta.inspect_redis_queues", return_value={"parking_depth": 0, "slack_depth": 0}),
        patch("app.backlog_eta.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.backlog_eta.entitlement_qualified_floor", return_value=70.0),
        patch("app.load_governor.load_governor_state", return_value=governor),
        patch(
            "app.site_watchdog.load_last_report",
            return_value={
                "ok": False,
                "checks": [{"name": "api_ready", "ok": False, "detail": "HTTP 503", "source": "droplet"}],
            },
        ),
    ):
        out = backlog_eta_summary(MagicMock(), settings)  # type: ignore[arg-type]

    triggers = out["server_load"]["pressure_triggers"]
    assert len(triggers) == 1
    assert triggers[0]["key"] == "site_watchdog_failed"
    assert "api_ready" in triggers[0]["detail"]
    assert any(row["key"] == "owner_outreach_briefs" for row in out["server_load"]["active_work"])
    assert "site health checks" in out["summary"]["decision"]
    assert not any("1,462,340 broad entitlement" in line for line in out["server_load"]["primary_drivers"])
    assert any(row["key"] == "broad_entitlement_coverage" for row in out["server_load"]["latent_gaps"])
