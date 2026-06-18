"""Tests for capacity-gated WA Phase B rollout scheduler."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.wa_phase_b_rollout import (
    county_ready_for_phase_b,
    load_phase_b_config,
    next_county_for_phase_b,
    wa_phase_b_cooldown_state,
    wa_phase_b_pending_merge_state,
)

_CONFIG = str(Path(__file__).resolve().parents[3] / "config/wa_phase_b_rollout.yaml")
_PILOT = str(Path(__file__).resolve().parents[3] / "config/pilot.yaml")


def test_next_county_for_phase_b_picks_benton_when_ready(monkeypatch) -> None:
    config = load_phase_b_config(_CONFIG)

    def fake_counts(_db, county_fips):
        return {f: (30_000 if f == "53005" else 0) for f in county_fips}

    def fake_missing(_db, county_fips):
        return {"total": 30_000, "missing_zoning": 30_000}

    monkeypatch.setattr("app.wa_phase_b_rollout.parcel_counts_by_county", fake_counts)
    monkeypatch.setattr("app.wa_phase_b_rollout.county_missing_zoning_stats", fake_missing)
    monkeypatch.setattr(
        "app.wa_phase_b_rollout.build_zoning_followup_summary",
        lambda **kwargs: {
            "counties": [
                {
                    "county_fips": "53005",
                    "needs_followup": True,
                    "zoning_status": "in_progress",
                    "jurisdiction_status_counts": {"source_found": 2},
                }
            ]
        },
    )

    county = next_county_for_phase_b(
        None,
        config=config,
        pilot_config_path=_PILOT,
        parcel_rollout_config={"county_fips_priority": ["53005"]},
    )
    assert county == "53005"


def test_county_ready_skips_when_zoning_mostly_present(monkeypatch) -> None:
    config = load_phase_b_config(_CONFIG)
    monkeypatch.setattr(
        "app.wa_phase_b_rollout.county_missing_zoning_stats",
        lambda _db, _fips: {"total": 100, "missing_zoning": 0},
    )
    ok, reason = county_ready_for_phase_b(
        None,
        county_fips="53005",
        config=config,
        followup_row={
            "needs_followup": True,
            "zoning_status": "in_progress",
            "jurisdiction_status_counts": {"source_found": 1},
        },
    )
    assert ok is False
    assert reason == "zoning_mostly_present"


def test_cooldown_blocks_recent_merge(monkeypatch) -> None:
    from datetime import UTC, datetime

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(
                action="wa_phase_b_county_merge_completed",
                entity_id="53005",
                created_at=datetime.now(UTC),
            )

    db = SimpleNamespace(execute=lambda *_args, **_kwargs: _Result())
    state = wa_phase_b_cooldown_state(db, {"min_hours_between_county_merges": 6})
    assert state["ready"] is False
    assert state["last_county_fips"] == "53005"


def test_pending_merge_locks_after_start(monkeypatch) -> None:
    from datetime import UTC, datetime

    started = SimpleNamespace(
        action="wa_phase_b_county_merge_started",
        entity_id="53005",
        created_at=datetime.now(UTC),
    )

    class _Result:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    calls = {"n": 0}

    def execute(_stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Result(started)
        return _Result(None)

    db = SimpleNamespace(execute=execute)
    state = wa_phase_b_pending_merge_state(db, {"pending_merge_lock_hours": 12})
    assert state["pending"] is True
    assert state["pending_county_fips"] == "53005"
