"""Tests for Baltimore Phase B follow-up after Pierce WA merge."""

from __future__ import annotations

from app.baltimore_phase_b import (
    BALTIMORE_CITY_FIPS,
    baltimore_needs_phase_b_merge,
    should_enqueue_baltimore_after_wa_county,
)
from app.config import Settings


def test_should_enqueue_after_pierce_when_enabled(monkeypatch) -> None:
    settings = Settings(
        baltimore_phase_b_after_pierce_enabled=True,
        baltimore_phase_b_overlay_path="/app/data/baltimore/baltimore_city_zoning_overlay.geojson",
    )
    monkeypatch.setattr("app.baltimore_phase_b.Path.is_file", lambda _self: True)
    ok, reason = should_enqueue_baltimore_after_wa_county(settings, "53053")
    assert ok is True
    assert reason == "ready"


def test_should_not_enqueue_for_other_counties() -> None:
    settings = Settings(baltimore_phase_b_after_pierce_enabled=True)
    ok, reason = should_enqueue_baltimore_after_wa_county(settings, "53033")
    assert ok is False
    assert reason == "not_trigger_county"


def test_should_not_enqueue_when_disabled() -> None:
    settings = Settings(baltimore_phase_b_after_pierce_enabled=False)
    ok, reason = should_enqueue_baltimore_after_wa_county(settings, "53053")
    assert ok is False
    assert reason == "baltimore_after_pierce_disabled"


def test_baltimore_needs_merge_when_gaps_exist(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.baltimore_phase_b.county_missing_zoning_stats",
        lambda _db, _fips: {"total": 223_139, "missing_zoning": 170_571},
    )
    needs, stats = baltimore_needs_phase_b_merge(None)
    assert needs is True
    assert stats["reason"] == "ready"
    assert stats["missing_pct"] > 50


def test_baltimore_skips_when_mostly_zoned(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.baltimore_phase_b.county_missing_zoning_stats",
        lambda _db, _fips: {"total": 1000, "missing_zoning": 5},
    )
    needs, stats = baltimore_needs_phase_b_merge(None)
    assert needs is False
    assert stats["reason"] == "zoning_mostly_present"


def test_baltimore_city_fips_constant() -> None:
    assert BALTIMORE_CITY_FIPS == "24510"
