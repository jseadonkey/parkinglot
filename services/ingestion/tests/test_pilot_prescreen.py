"""Tests for pilot parcel pre-ingest funnel."""

from __future__ import annotations

from pathlib import Path

from parking_ingestion.pilot_prescreen import (
    PrescreenConfig,
    PilotParcelPrescreener,
    load_prescreen_config,
    zoning_prescreen_pass,
)

_REPO = Path(__file__).resolve().parents[3]


def test_load_prescreen_config_excludes_residential() -> None:
    cfg = load_prescreen_config(_REPO / "config/pilot_parcel_prescreen.yaml")
    assert 11 in cfg.exclude_landuse_codes
    assert cfg.min_sqft >= 5000


def test_zoning_drop_explicit_false_keeps_unknown() -> None:
    rules = {"default_when_unknown": False, "jurisdictions": {"kent_city": {"zones": {}}}}
    assert zoning_prescreen_pass("NR-2", "kent_city", rules, mode="drop_explicit_false")
    rules["jurisdictions"]["kent_city"]["zones"]["R-1"] = {"allows_surface_parking": False}
    assert not zoning_prescreen_pass("R-1", "kent_city", rules, mode="drop_explicit_false")


def test_prescreener_rejects_small_residential_in_kent() -> None:
    prescreen = PrescreenConfig(
        geography_enabled=False,
        land_use_enabled=True,
        exclude_landuse_codes={11},
        lot_size_enabled=True,
        min_sqft=5000,
        zoning_enabled=False,
    )
    ps = PilotParcelPrescreener(
        pilot_config_path=_REPO / "config/pilot.yaml",
        prescreen=prescreen,
        zoning_lookup=None,
    )
    feat = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-122.24, 47.38],
                    [-122.239, 47.38],
                    [-122.239, 47.381],
                    [-122.24, 47.381],
                    [-122.24, 47.38],
                ]
            ],
        },
        "properties": {"LANDUSE_CD": 11, "Shape__Area": 8000, "PARCEL_ID_NR": "TEST-1"},
    }
    keep, _, reason = ps.evaluate_feature(feat)
    assert not keep
    assert reason == "land_use"


def test_prescreener_rejects_built_out_parcel() -> None:
    prescreen = PrescreenConfig(
        geography_enabled=False,
        building_value_enabled=True,
        max_building_share=0.70,
        zoning_enabled=False,
        land_use_enabled=False,
        lot_size_enabled=False,
    )
    ps = PilotParcelPrescreener(
        pilot_config_path=_REPO / "config/pilot.yaml",
        prescreen=prescreen,
        zoning_lookup=None,
    )
    feat = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-122.24, 47.38],
                    [-122.239, 47.38],
                    [-122.239, 47.381],
                    [-122.24, 47.381],
                    [-122.24, 47.38],
                ]
            ],
        },
        "properties": {
            "PARCEL_ID_NR": "TEST-BLDG",
            "VALUE_LAND": 100_000,
            "VALUE_BLDG": 400_000,
        },
    }
    keep, _, reason = ps.evaluate_feature(feat)
    assert not keep
    assert reason == "building_value"
