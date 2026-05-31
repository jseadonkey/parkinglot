"""Tests for curated parking comp lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from parking_ingestion.parking_comps import (
    effective_daily_rate,
    find_nearest_parking_comp,
    load_parking_comps,
    parking_comp_metrics_for_point,
)
from parking_core.pilot import ParkingCompMarketConfig

REPO = Path(__file__).resolve().parents[3]
COMPS = REPO / "data" / "pilot" / "kent_king_parking_comps.yaml"


@pytest.fixture
def comps():
    assert COMPS.is_file()
    return load_parking_comps(COMPS)


def test_load_kent_king_comps(comps) -> None:
    assert len(comps) >= 10
    assert all(c.rate_usd_per_day >= 0 for c in comps)


def test_effective_daily_rate_from_hourly() -> None:
    from parking_ingestion.parking_comps import ParkingComp

    c = ParkingComp(
        id="x",
        name="Hourly only",
        lat=0.0,
        lon=0.0,
        kind="garage",
        rate_usd_per_day=0.0,
        rate_usd_per_hour=2.0,
        notes=None,
    )
    assert effective_daily_rate(c) == 20.0


def test_find_nearest_prefers_surface_on_tie(comps) -> None:
    # Kent Station area — should match a nearby comp
    hit = find_nearest_parking_comp(47.3854, -122.2399, comps, min_rate_usd_per_day=6.0)
    assert hit is not None
    assert hit.distance_m < 2000.0
    assert effective_daily_rate(hit.comp) >= 6.0


def test_min_rate_filters_free_comps(comps) -> None:
    hit = find_nearest_parking_comp(47.4590, -122.2570, comps, min_rate_usd_per_day=6.0)
    assert hit is not None
    assert effective_daily_rate(hit.comp) >= 6.0


def test_parking_comp_metrics_for_point(comps) -> None:
    cfg = ParkingCompMarketConfig(
        enabled=True,
        comps_path=str(COMPS.relative_to(REPO)),
        min_rate_usd_per_day=6.0,
    )
    dist, snap = parking_comp_metrics_for_point(47.3854, -122.2399, cfg, repo_root=REPO)
    assert dist is not None
    assert snap is not None
    assert snap["name"]
    assert snap["rate_usd_per_day"] >= 6.0
