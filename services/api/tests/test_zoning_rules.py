from __future__ import annotations

from pathlib import Path

from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict
from parking_ingestion.zoning_rules import (
    load_zoning_rules,
    lookup_zone_entry,
    normalize_zone_code,
    resolve_surface_parking,
    zone_lookup_candidates,
)


def test_normalize_zone_code() -> None:
    assert normalize_zone_code(" c-1 ") == "C-1"
    assert normalize_zone_code(None) == ""


def test_resolve_explicit_override() -> None:
    rules = {"default_when_unknown": False, "jurisdictions": {}}
    assert resolve_surface_parking("X", "kent_city", True, rules) is True
    assert resolve_surface_parking("X", "kent_city", False, rules) is False


def test_resolve_zone_lookup() -> None:
    rules = {
        "default_when_unknown": False,
        "jurisdictions": {
            "kent_city": {
                "zones": {
                    "C-1": {"allows_surface_parking": True, "note": "t"},
                }
            },
            "king_unincorporated": {
                "zones": {
                    "CB": {"allows_surface_parking": True, "note": "community business"},
                }
            },
        },
    }
    assert resolve_surface_parking("c-1", "kent_city", None, rules) is True
    assert resolve_surface_parking("UNKNOWN", "kent_city", None, rules) is False
    assert resolve_surface_parking("CB-SO", "king_unincorporated", None, rules) is True


def test_zone_suffix_fallback_candidates() -> None:
    assert zone_lookup_candidates("R-6-P-SO") == ["R-6-P-SO", "R-6-P", "R-6"]
    assert zone_lookup_candidates("GC-MU") == ["GC-MU"]


def test_load_zoning_rules_missing_returns_safe_default(tmp_path: Path) -> None:
    assert load_zoning_rules(tmp_path / "nope.yaml") == {"default_when_unknown": False, "jurisdictions": {}}


def test_loader_inference_from_rules_file(tmp_path: Path) -> None:
    rules_yaml = tmp_path / "rules.yaml"
    rules_yaml.write_text(
        """version: 1
default_when_unknown: false
jurisdictions:
  kent_city:
    zones:
      "GC":
        allows_surface_parking: true
        note: "test"
"""
    )
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {
                    "PIN": "KC-002",
                    "COUNTY_FIPS": "53033",
                    "ZONING": "GC",
                    "ZONING_JURISDICTION": "kent_city",
                },
            }
        ],
    }
    attrs, _ = list(iter_parcels_from_geojson_dict(fc, rules_path=rules_yaml))[0]
    assert attrs["zoning_allows_surface_parking"] is True


def test_loader_explicit_override_beats_yaml(tmp_path: Path) -> None:
    rules_yaml = tmp_path / "rules.yaml"
    rules_yaml.write_text(
        """version: 1
default_when_unknown: false
jurisdictions:
  kent_city:
    zones:
      "GC":
        allows_surface_parking: true
"""
    )
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {
                    "PIN": "KC-003",
                    "COUNTY_FIPS": "53033",
                    "ZONING": "GC",
                    "ZONING_JURISDICTION": "kent_city",
                    "ZONING_ALLOWS_SURFACE_PARKING": False,
                },
            }
        ],
    }
    attrs, _ = list(iter_parcels_from_geojson_dict(fc, rules_path=rules_yaml))[0]
    assert attrs["zoning_allows_surface_parking"] is False
