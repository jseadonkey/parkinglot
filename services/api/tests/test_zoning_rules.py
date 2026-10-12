from __future__ import annotations

from pathlib import Path

from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict
from parking_ingestion.zoning_rules import (
    infer_zoning_jurisdiction,
    load_effective_zoning_rules,
    load_zoning_rules,
    merge_zoning_rules,
    normalize_zone_code,
    resolve_principal_use_symbol,
    resolve_surface_parking,
    zoning_entitlement_tier,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


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
            }
        },
    }
    assert resolve_surface_parking("c-1", "kent_city", None, rules) is True
    assert resolve_surface_parking("UNKNOWN", "kent_city", None, rules) is False


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


def test_loader_string_false_override_is_not_truthy(tmp_path: Path) -> None:
    rules_yaml = tmp_path / "rules.yaml"
    rules_yaml.write_text(
        """version: 1
default_when_unknown: false
jurisdictions:
  pasco_city:
    zones:
      "C-2":
        allows_surface_parking: true
        principal_use_symbol: P
"""
    )
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {
                    "PIN": "PA-001",
                    "COUNTY_FIPS": "53005",
                    "ZONING": "C-2",
                    "ZONING_JURISDICTION": "pasco_city",
                    "ZONING_ALLOWS_SURFACE_PARKING": "false",
                },
            }
        ],
    }
    attrs, _ = list(iter_parcels_from_geojson_dict(fc, rules_path=rules_yaml))[0]
    assert attrs["zoning_allows_surface_parking"] is False


def test_infer_zoning_jurisdiction_baltimore_city() -> None:
    assert infer_zoning_jurisdiction("24510", None) == "baltimore_city"
    assert infer_zoning_jurisdiction("24510", "custom") == "custom"
    assert infer_zoning_jurisdiction("53033", None) is None


def test_merge_zoning_rules_combines_jurisdictions() -> None:
    wa = {"default_when_unknown": False, "jurisdictions": {"kent_city": {"zones": {"GC": True}}}}
    md = {"default_when_unknown": False, "jurisdictions": {"baltimore_city": {"zones": {"C-5": True}}}}
    merged = merge_zoning_rules(wa, md)
    assert "kent_city" in merged["jurisdictions"]
    assert "baltimore_city" in merged["jurisdictions"]


def test_load_effective_zoning_rules_includes_baltimore(tmp_path: Path) -> None:
    rules = load_effective_zoning_rules()
    bc = REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml"
    if bc.is_file():
        assert "baltimore_city" in (rules.get("jurisdictions") or {})
        assert resolve_surface_parking("C-3", "baltimore_city", None, rules) is True
        assert resolve_surface_parking("C-5", "baltimore_city", None, rules) is False
        assert resolve_surface_parking("I-1", "baltimore_city", None, rules) is True
        assert resolve_surface_parking("C-1", "baltimore_city", None, rules) is False


def test_benton_rules_only_score_ordinance_confirmed_pasco_c2() -> None:
    rules = load_effective_zoning_rules()
    assert resolve_principal_use_symbol("C-2", "pasco_city", rules) == "P"
    assert zoning_entitlement_tier(resolve_principal_use_symbol("C-2", "pasco_city", rules)) == "permitted"
    assert resolve_surface_parking("C-2", "pasco_city", None, rules) is True

    assert resolve_principal_use_symbol("C-1", "kennewick_city", rules) == "NEEDS_REVIEW"
    assert zoning_entitlement_tier(resolve_principal_use_symbol("C-1", "kennewick_city", rules)) == "unknown"
    assert resolve_surface_parking("C-1", "kennewick_city", None, rules) is False

    assert resolve_principal_use_symbol("COMMERCIAL", "benton_unincorporated", rules) == "NEEDS_REVIEW"
    assert zoning_entitlement_tier(
        resolve_principal_use_symbol("COMMERCIAL", "benton_unincorporated", rules)
    ) == "unknown"
    assert resolve_surface_parking("COMMERCIAL", "benton_unincorporated", None, rules) is False


def test_loader_baltimore_jurisdiction_inferred_from_fips(tmp_path: Path) -> None:
    rules_yaml = tmp_path / "md.yaml"
    rules_yaml.write_text(
        """version: 1
default_when_unknown: false
jurisdictions:
  baltimore_city:
    zones:
      "C-3":
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
                    "PIN": "BC-001",
                    "COUNTY_FIPS": "24510",
                    "ZONING": "C-3",
                },
            }
        ],
    }
    attrs, _ = list(iter_parcels_from_geojson_dict(fc, rules_path=rules_yaml))[0]
    assert attrs["zoning_allows_surface_parking"] is True
