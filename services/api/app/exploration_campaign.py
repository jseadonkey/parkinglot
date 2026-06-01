"""Washington statewide exploration: rotate county GeoJSON ingests across a fixed calendar window."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml


def load_campaign_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def campaign_day_index(start: date, today: date, duration_days: int) -> int | None:
    """Return 0-based day offset since ``start``, or None if outside ``[start, start + duration_days)``."""
    if duration_days < 1:
        return None
    if today < start:
        return None
    end = start + timedelta(days=duration_days)
    if today >= end:
        return None
    return (today - start).days


def counties_for_exploration_day(sorted_counties: list[str], day_index: int) -> list[str]:
    """Round-robin bucket: county list index ``i`` maps to day ``i % 7`` (repeats after 7 days)."""
    bucket = day_index % 7
    return [c for i, c in enumerate(sorted_counties) if i % 7 == bucket]
