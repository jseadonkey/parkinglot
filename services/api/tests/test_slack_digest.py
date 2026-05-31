"""Slack digest content — funnel-aware messaging."""

from __future__ import annotations

from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from app.slack_digest import (
    _format_window_label,
    _rationale_line,
    build_slack_digest_blocks,
    build_qualified_parcels_report_blocks,
)


def test_format_window_label() -> None:
    assert _format_window_label(20) == "20m"
    assert _format_window_label(60) == "1h"
    assert _format_window_label(120) == "2h"


def test_rationale_line_strategic_no_comp() -> None:
    line = _rationale_line(
        {
            "zoning_component": 25,
            "lot_size_component": 20,
            "corner_component": 0,
            "demand_proximity_component": 0,
        },
        total=45,
        floor=52,
        qualified=False,
        profile=STRATEGIC,
        pilot_snapshot={"demand_signal_source": "none"},
    )
    assert "no comp credit" in line
    assert "below floor" in line


def test_rationale_line_entitlement_poi() -> None:
    line = _rationale_line(
        {
            "zoning_component": 40,
            "lot_size_component": 20,
            "corner_component": 10,
            "demand_proximity_component": 30,
        },
        total=100,
        floor=55,
        qualified=True,
        profile=ENTITLEMENT,
        pilot_snapshot={"demand_signal_source": "poi"},
    )
    assert "POI demand" in line
    assert "meets floor" in line


def test_rationale_line_identification_prescreen() -> None:
    line = _rationale_line(
        {
            "zoning_component": 45,
            "lot_size_component": 25,
            "corner_component": 0,
            "demand_proximity_component": 0,
        },
        total=70,
        floor=45,
        qualified=True,
        profile=IDENTIFICATION,
    )
    assert "prescreen only" in line


def test_build_slack_digest_blocks_structure(monkeypatch) -> None:
    from app.slack_digest import FunnelMetrics, _build_funnel_metrics

    fake = FunnelMetrics(
        in_scope_parcels=1000,
        total_parcels=1200,
        with_identification=1000,
        with_entitlement=400,
        with_strategic=400,
        dual_qualified=25,
        with_parking_comp=10,
        candidate_target=125_000,
        ingest_phase="scoring_backlog",
        ingest_headline="Scoring backlog in progress",
    )
    monkeypatch.setattr("app.slack_digest._build_funnel_metrics", lambda _db, _s: fake)
    monkeypatch.setattr(
        "app.slack_digest.query_deal_progress_board",
        lambda *a, **k: ({"approved_ready": 5, "screened_out": 300}, []),
    )
    monkeypatch.setattr("app.slack_digest._count_since", lambda *a: 0)
    monkeypatch.setattr("app.slack_digest._count_audit_action_since", lambda *a: 0)
    monkeypatch.setattr("app.slack_digest._parcel_score_counts_since", lambda *a: {})
    monkeypatch.setattr("app.slack_digest._workflow_status_since", lambda *a: {})
    monkeypatch.setattr("app.slack_digest._pending_approvals", lambda *a: 2)
    monkeypatch.setattr("app.slack_digest._recent_audit_lines", lambda *a: [])
    monkeypatch.setattr("app.slack_digest.load_pilot_config", lambda _p: type("P", (), {"region": type("R", (), {"name": "Test"})(), "scoring": type("S", (), {"qualified_min_score": 55})()})())

    class FakeSession:
        def scalar(self, *_a, **_k):
            return 0

    blocks, fallback = build_slack_digest_blocks(FakeSession(), window_minutes=20)
    text = fallback + " ".join(str(b) for b in blocks)
    assert "Three scoring agents" in text
    assert "Cartographer" in text
    assert "Dual-qualified" in text
    assert "Deal progress" in text
    assert "125" in text or "125000" in text.replace(",", "")


def test_build_qualified_report_mentions_dual(monkeypatch) -> None:
    from app.config import Settings
    from app.slack_digest import FunnelMetrics, _build_funnel_metrics, _paired_latest_scores

    monkeypatch.setattr(
        "app.slack_digest._build_funnel_metrics",
        lambda _db, _s: FunnelMetrics(
            in_scope_parcels=100,
            total_parcels=100,
            with_identification=100,
            with_entitlement=50,
            with_strategic=50,
            dual_qualified=3,
            with_parking_comp=1,
            candidate_target=100,
            ingest_phase="idle",
            ingest_headline="Idle",
        ),
    )
    monkeypatch.setattr("app.slack_digest._paired_latest_scores", lambda _db: [])

    class FakeSession:
        pass

    blocks, fallback = build_qualified_parcels_report_blocks(FakeSession(), settings=Settings())
    joined = fallback + str(blocks)
    assert "Dual-qualified" in joined
    assert "Beacon-led" in joined
