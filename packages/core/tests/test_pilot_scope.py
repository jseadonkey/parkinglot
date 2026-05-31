"""Tests for King/Kent geographic pilot scope."""

from __future__ import annotations

from pathlib import Path

from parking_core.pilot import InScopeConfig, RegionConfig
from parking_core.pilot_scope import classify_king_kent_scope

_REPO = Path(__file__).resolve().parents[3]
_KENT = _REPO / "data/boundaries/wa/kent_city_census_places.geojson"
_EXCL = _REPO / "data/boundaries/wa/king_county_incorporated_excluding_kent.geojson"


def test_kent_station_centroid_in_scope() -> None:
    assert classify_king_kent_scope(
        -122.2399,
        47.3854,
        kent_boundary_geojson=_KENT,
        excluded_incorporated_geojson=_EXCL,
        repo_root=_REPO,
    )


def test_seattle_downtown_out_of_scope() -> None:
    assert not classify_king_kent_scope(
        -122.3321,
        47.6062,
        kent_boundary_geojson=_KENT,
        excluded_incorporated_geojson=_EXCL,
        repo_root=_REPO,
    )


def test_classify_from_in_scope_config_model() -> None:
    from parking_core.pilot_scope import classify_from_in_scope_config

    cfg = InScopeConfig(
        kent_city_boundary_geojson=str(_KENT.relative_to(_REPO)),
        excluded_incorporated_places_geojson=str(_EXCL.relative_to(_REPO)),
    )
    assert classify_from_in_scope_config(-122.24, 47.385, cfg, repo_root=_REPO)
    assert not classify_from_in_scope_config(-122.33, 47.61, cfg, repo_root=_REPO)
