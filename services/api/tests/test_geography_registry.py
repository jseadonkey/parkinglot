from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point

from parking_core.city_inventory import load_city_inventory_manifest
from parking_core.geography_registry import load_geography_registry, validate_geography_registry
from parking_core.pilot import load_pilot_config
from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict
from parking_ingestion.jurisdiction_resolver import resolve_zoning_jurisdiction
from parking_ingestion.zoning_rules import infer_zoning_jurisdiction, load_effective_zoning_rules

REPO_ROOT = Path(__file__).resolve().parents[3]
WA_CITY_MANIFEST = REPO_ROOT / "data/boundaries/wa/manifest/wa_incorporated_places.json"


def _square(x0: float, y0: float, size: float = 1.0) -> dict:
    x1, y1 = x0 + size, y0 + size
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def test_registry_covers_every_pilot_county_with_default_jurisdiction() -> None:
    registry = load_geography_registry(REPO_ROOT / "config/geography_registry.yaml")
    pilot = load_pilot_config(REPO_ROOT / "config/pilot.yaml")

    missing = [
        county
        for county in pilot.region.county_fips
        if registry.default_jurisdiction_for_county(county) is None
    ]

    assert missing == []
    assert registry.default_jurisdiction_for_county("24510") == "baltimore_city"
    assert registry.default_jurisdiction_for_county("53033") == "king_unincorporated"
    assert registry.default_jurisdiction_for_county("53053") == "wa_53053_unincorporated"


def test_registry_has_city_inventory_sources_for_pilot_states() -> None:
    registry = load_geography_registry(REPO_ROOT / "config/geography_registry.yaml")
    city_inventory_states = {source.state_fips for source in registry.city_inventory_sources}

    assert {"24", "53"}.issubset(city_inventory_states)
    assert registry.geography_for_jurisdiction("kent_city") is not None


def test_wa_city_manifest_covers_all_incorporated_places() -> None:
    manifest = load_city_inventory_manifest(WA_CITY_MANIFEST)

    assert manifest.place_count == 281
    assert len(manifest.entries) == 281
    assert manifest.county_slice_count >= 281
    assert set(manifest.lsadc_counts) == {"25", "43"}
    assert manifest.entry_by_geoid()["5335415"].jurisdiction_key == "kent_city"


def test_registry_wa_city_agents_match_manifest() -> None:
    registry = load_geography_registry(REPO_ROOT / "config/geography_registry.yaml")
    manifest = load_city_inventory_manifest(WA_CITY_MANIFEST)
    city_agents = [
        geo
        for geo in registry.geographies
        if geo.type == "city" and geo.state_fips == "53" and geo.boundary_path
    ]

    for entry in manifest.entries:
        assert any(
            geo.jurisdiction_key == entry.jurisdiction_key and geo.boundary_path == entry.boundary_path
            for geo in city_agents
        ), entry.geoid
        for county in entry.county_fips:
            assert any(
                geo.jurisdiction_key == entry.jurisdiction_key
                and geo.boundary_path == entry.boundary_path
                and geo.county_fips == county
                for geo in city_agents
            ), f"{entry.geoid}:{county}"


def test_wa_city_rules_skeleton_has_manifest_jurisdictions() -> None:
    manifest = load_city_inventory_manifest(WA_CITY_MANIFEST)
    rules = load_effective_zoning_rules()
    jurisdictions = rules.get("jurisdictions") or {}

    missing = sorted(manifest.jurisdiction_keys() - set(jurisdictions))

    assert missing == []


def test_registry_validation_has_no_structural_errors() -> None:
    registry = load_geography_registry(REPO_ROOT / "config/geography_registry.yaml")
    pilot = load_pilot_config(REPO_ROOT / "config/pilot.yaml")
    rules = load_effective_zoning_rules()
    issues = validate_geography_registry(registry, pilot_county_fips=pilot.region.county_fips, zoning_rules=rules)

    assert [issue for issue in issues if issue.severity == "error"] == []


def test_infer_zoning_jurisdiction_uses_registry_defaults() -> None:
    assert infer_zoning_jurisdiction("53033", None) == "king_unincorporated"
    assert infer_zoning_jurisdiction("53053", None) == "wa_53053_unincorporated"
    assert infer_zoning_jurisdiction("24510", None) == "baltimore_city"


def test_resolver_uses_city_boundary_before_county_default(tmp_path: Path) -> None:
    boundary = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": _square(0, 0, 2), "properties": {"name": "Test City"}}],
    }
    boundary_path = tmp_path / "test_city.geojson"
    boundary_path.write_text(json.dumps(boundary))

    registry_yaml = tmp_path / "registry.yaml"
    registry_yaml.write_text(
        f"""
version: 1
sources: []
geographies:
  - key: test_city
    name: Test City
    type: city
    state_fips: "53"
    county_fips: "53033"
    jurisdiction_key: test_city
    boundary_path: "{boundary_path}"
  - key: test_county_unincorporated
    name: Test County unincorporated
    type: county_unincorporated
    state_fips: "53"
    county_fips: "53033"
    jurisdiction_key: test_unincorporated
    default_for_county: true
"""
    )
    registry = load_geography_registry(registry_yaml)

    assert resolve_zoning_jurisdiction("53033", None, geom=Point(1, 1), registry=registry) == "test_city"
    assert resolve_zoning_jurisdiction("53033", None, geom=Point(5, 5), registry=registry) == "test_unincorporated"


def test_resolver_uses_generated_wa_city_boundaries() -> None:
    registry = load_geography_registry(REPO_ROOT / "config/geography_registry.yaml")

    assert (
        resolve_zoning_jurisdiction("53033", None, geom=Point(-122.3321, 47.6062), registry=registry)
        == "seattle_city"
    )
    assert (
        resolve_zoning_jurisdiction("53063", None, geom=Point(-117.4260, 47.6588), registry=registry)
        == "spokane_city"
    )
    assert resolve_zoning_jurisdiction("53033", None, geom=Point(-122.2348, 47.3809), registry=registry) == "kent_city"


def test_loader_persists_registry_resolved_jurisdiction() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(10, 10, 1),
                "properties": {
                    "PIN": "PC-001",
                    "COUNTY_FIPS": "53053",
                    "ZONING": "UNKNOWN",
                },
            }
        ],
    }

    attrs, _ = list(iter_parcels_from_geojson_dict(fc))[0]

    assert attrs["zoning_jurisdiction"] == "wa_53053_unincorporated"
    assert attrs["raw_properties"]["ZONING_JURISDICTION"] == "wa_53053_unincorporated"
