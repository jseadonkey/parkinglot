"""Tests for Phase B overlay coverage validation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.phase_b_overlay_validation import min_overlay_coverage_pct, validate_overlay_for_county_merge


def _write_overlay(path: Path, county_fips: str, n: int) -> None:
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            },
            "properties": {
                "APN": f"APN-{i}",
                "COUNTY_FIPS": county_fips,
                "ZONING": "R-1",
            },
        }
        for i in range(n)
    ]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def test_min_overlay_coverage_pct_tiers() -> None:
    assert min_overlay_coverage_pct(223_139) == 20.0
    assert min_overlay_coverage_pct(100_000) == 20.0
    assert min_overlay_coverage_pct(50_000) == 10.0
    assert min_overlay_coverage_pct(15_000) == 10.0
    assert min_overlay_coverage_pct(5_000) == 5.0


def test_validate_rejects_baltimore_thin_sample(tmp_path: Path, monkeypatch) -> None:
    overlay = tmp_path / "overlay.geojson"
    _write_overlay(overlay, "24510", 1_500)

    class _Db:
        def scalar(self, _stmt):
            return 20_000

    monkeypatch.setattr(
        "app.phase_b_overlay_validation.load_pilot_config",
        lambda _p: SimpleNamespace(region=SimpleNamespace(county_fips=["24510"])),
    )

    result = validate_overlay_for_county_merge(
        _Db(),  # type: ignore[arg-type]
        overlay,
        "24510",
        pilot_config_path="config/pilot.yaml",
        min_coverage_pct=10.0,
    )
    assert result["ok"] is False
    assert result["reason"] == "overlay_coverage_below_minimum"


def test_validate_accepts_adequate_coverage(tmp_path: Path, monkeypatch) -> None:
    overlay = tmp_path / "overlay.geojson"
    _write_overlay(overlay, "53053", 5_000)

    class _Db:
        def scalar(self, _stmt):
            return 20_000

    monkeypatch.setattr(
        "app.phase_b_overlay_validation.load_pilot_config",
        lambda _p: SimpleNamespace(region=SimpleNamespace(county_fips=["53053"])),
    )

    result = validate_overlay_for_county_merge(
        _Db(),  # type: ignore[arg-type]
        overlay,
        "53053",
        pilot_config_path="config/pilot.yaml",
        min_coverage_pct=10.0,
    )
    assert result["ok"] is True
    assert result["coverage_pct"] == 25.0
