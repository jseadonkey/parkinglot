from __future__ import annotations

from pathlib import Path

from app.geo_scope import (
    aerial_enrich_max_rows,
    list_performance,
    load_geo_scope,
    should_skip_poi_seed,
    vacant_overfetch,
)

_REPO = Path(__file__).resolve().parents[3]
_GEO_SCOPE = str(_REPO / "config/geo_scope.yaml")


def test_geo_scope_principles_present() -> None:
    raw = load_geo_scope(_GEO_SCOPE)
    assert "principles" in raw
    assert "global" in raw["principles"]
    assert "list_performance" in raw


def test_list_performance_budgets() -> None:
    perf = list_performance(_GEO_SCOPE)
    assert perf["vacant_overfetch_cap"] == 75
    assert perf["aerial_enrich_max_rows"] == 40
    assert vacant_overfetch(25, _GEO_SCOPE) == 75
    assert aerial_enrich_max_rows(_GEO_SCOPE) == 40


def test_poi_seed_skips_state_scope_not_small_county() -> None:
    assert should_skip_poi_seed(state_scope=True, path=_GEO_SCOPE) is True
    assert (
        should_skip_poi_seed(state_scope=False, geography_parcel_count=5_000, path=_GEO_SCOPE)
        is False
    )
    assert (
        should_skip_poi_seed(state_scope=False, geography_parcel_count=200_000, path=_GEO_SCOPE)
        is True
    )
