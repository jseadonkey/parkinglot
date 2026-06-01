"""Statewide exploration schedule (pure date / county math — no DB)."""

from __future__ import annotations

from datetime import date

from app.config import Settings
from app.exploration_campaign import campaign_day_index, counties_for_exploration_day


def test_settings_exploration_start_date_empty_env(monkeypatch) -> None:
    monkeypatch.setenv("EXPLORATION_CAMPAIGN_START_DATE", "")
    s = Settings()
    assert s.exploration_campaign_start_date is None


def test_campaign_day_index_seven_day_window() -> None:
    start = date(2026, 5, 1)
    assert campaign_day_index(start, date(2026, 4, 30), 7) is None
    assert campaign_day_index(start, date(2026, 5, 1), 7) == 0
    assert campaign_day_index(start, date(2026, 5, 7), 7) == 6
    assert campaign_day_index(start, date(2026, 5, 8), 7) is None


def test_counties_round_robin_covers_all_in_week() -> None:
    counties = [f"{i:05d}" for i in range(53001, 53078, 2)]  # 39 WA-like codes
    assert len(counties) == 39
    seen: set[str] = set()
    for d in range(7):
        bucket = counties_for_exploration_day(counties, d)
        seen.update(bucket)
    assert seen == set(counties)


def test_day_bucket_stable() -> None:
    c = ["53001", "53003", "53005", "53007"]
    assert counties_for_exploration_day(c, 0) == ["53001"]
    assert counties_for_exploration_day(c, 1) == ["53003"]
    assert counties_for_exploration_day(c, 8) == ["53003"]  # day_index % 7 == 1
