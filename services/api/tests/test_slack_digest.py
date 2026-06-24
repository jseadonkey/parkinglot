"""Slack digest blocks and reporting catalog."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.slack_digest import (
    build_ingest_agent_mrkdwn,
    build_slack_digest_blocks,
    slack_agent_event_updates_enabled,
    slack_reporting_catalog,
)


def test_slack_reporting_catalog_includes_core_reports() -> None:
    s = Settings(
        slack_digest_channel_id="C_DIGEST",
        slack_agent_discussion_channel_id="C_AGENTS",
        site_watchdog_enabled=True,
        site_watchdog_slack_channel_id="C_WATCH",
    )
    ids = {row["id"] for row in slack_reporting_catalog(s)}
    assert "standup" in ids
    assert "qualified_parcels" in ids
    assert "dual_agent" in ids
    assert "site_watchdog" in ids


def test_slack_reporting_catalog_includes_agent_events_when_enabled() -> None:
    s = Settings(slack_agent_event_updates="1", slack_digest_channel_id="C1")
    ids = {row["id"] for row in slack_reporting_catalog(s)}
    assert "agent_events" in ids


def test_build_slack_digest_blocks_includes_readiness_and_catalog() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.execute.return_value.all.return_value = []
    db.scalars.return_value = iter([])
    empty_readiness = {
        "parcel_row_total": 0,
        "parcels_missing_zoning_code": {"count": 0, "pct": 0},
        "parcels_missing_distance_to_nearest_demand_m": {"count": 0, "pct": 0},
        "parcels_pipeline_funnel_backlog": {"count": 0, "pct": 0},
        "parcels_missing_owner_outreach_brief": {"count": 0, "pct": 0},
        "parcels_prescreen_qualified": {"count": 0, "floor": 50},
    }
    scope_stub = {
        "region_name": "Test region",
        "counties_with_ingested_parcels": 0,
        "pilot_county_count": 2,
        "parcels_in_pilot_counties": 0,
        "primary_market_name": "Test market",
        "parcels_in_priority_counties": 0,
        "counties": [],
    }
    with (
        patch("app.slack_digest.export_readiness_summary", return_value=empty_readiness),
        patch("app.slack_digest.pilot_scope_summary", return_value=scope_stub),
    ):
        blocks, _fallback = build_slack_digest_blocks(
            db,
            hours=2,
            settings=Settings(slack_digest_channel_id="C1"),
        )
    section_text = str(blocks)
    assert "Data gathering & progress" in section_text
    assert "What we're gathering" in section_text
    assert "Ingest agent" in section_text
    assert "Baltimore City" in section_text
    assert "parcels.created_at" in section_text
    assert "Other Slack reports" in section_text
    assert "Pipeline activity" in section_text


def test_build_ingest_agent_explains_refresh_vs_new_rows() -> None:
    db = MagicMock()
    db.scalar.return_value = 0
    db.execute.return_value.all.return_value = []
    db.scalars.return_value = iter([])
    scope_stub = {
        "primary_market_name": "Baltimore, Maryland",
        "priority_county_fips": ["24510"],
        "counties": [{"county_fips": "24510", "county_name": "Baltimore City", "parcels_in_db": 1052}],
    }
    ingest = {
        "runs": 1,
        "inserted": 0,
        "updated": 20000,
        "skipped": 0,
        "merge_runs": 0,
        "merge_updated": 0,
        "merge_not_found": 0,
    }
    with patch("app.slack_digest.pilot_scope_summary", return_value=scope_stub):
        text = build_ingest_agent_mrkdwn(
            db,
            Settings(wa_statewide_rollout_enabled=False),
            hours=1,
            cutoff=datetime.now(tz=UTC),
            ingest=ingest,
            new_parcel_rows=0,
        )
    assert "refreshed existing APNs" in text
    assert "New parcel rows" in text


def test_slack_agent_event_updates_enabled_parsing() -> None:
    assert slack_agent_event_updates_enabled(Settings(slack_agent_event_updates="on")) is True
    assert slack_agent_event_updates_enabled(Settings(slack_agent_event_updates="")) is False
