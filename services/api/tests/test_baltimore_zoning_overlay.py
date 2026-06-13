from __future__ import annotations

import json
from pathlib import Path

from parking_ingestion.baltimore_zoning_overlay import build_zoning_overlay_geojson
from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict

REPO_ROOT = Path(__file__).resolve().parents[3]


def _square(x0: float, y0: float, size: float = 1.0) -> dict:
    x1, y1 = x0 + size, y0 + size
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def test_build_zoning_overlay_assigns_zone_inside_district() -> None:
    parcels = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0.5, 0.5, 0.1),
                "properties": {"APN": "BC-TEST-1", "COUNTY_FIPS": "24510"},
            }
        ],
    }
    zoning = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0, 0, 2),
                "properties": {"Zoning": "C-5"},
            }
        ],
    }
    overlay = build_zoning_overlay_geojson(parcels, zoning)
    assert len(overlay["features"]) == 1
    props = overlay["features"][0]["properties"]
    assert props["ZONING"] == "C-5"
    assert props["ZONING_JURISDICTION"] == "baltimore_city"
    assert props["APN"] == "BC-TEST-1"


def test_overlay_loader_scores_c3_allowed(tmp_path: Path) -> None:
    parcels = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0.5, 0.5, 0.1),
                "properties": {"APN": "BC-TEST-2", "COUNTY_FIPS": "24510"},
            }
        ],
    }
    zoning = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0, 0, 2),
                "properties": {"Zoning": "C-3"},
            }
        ],
    }
    overlay = build_zoning_overlay_geojson(parcels, zoning)
    rules = REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml"
    attrs, _ = list(iter_parcels_from_geojson_dict(overlay, rules_path=rules if rules.is_file() else None))[0]
    assert attrs["zoning_code"] == "C-3"
    assert attrs["zoning_allows_surface_parking"] is True


def test_loader_reads_baltimore_realproperty_zonecode() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0, 0),
                "properties": {
                    "APN": "MD-BALT-CITY-0592043",
                    "COUNTY_FIPS": "24510",
                    "ZONECODE": "C-5DC",
                },
            }
        ],
    }
    rules = REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml"
    attrs, _ = list(iter_parcels_from_geojson_dict(fc, rules_path=rules if rules.is_file() else None))[0]
    assert attrs["zoning_code"] == "C-5DC"
    assert attrs["zoning_principal_use_symbol"] == "CB"
    assert attrs["zoning_entitlement_tier"] == "conditional"


def test_build_overlay_skips_parcels_without_apn() -> None:
    parcels = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _square(0.5, 0.5), "properties": {}},
        ],
    }
    zoning = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _square(0, 0, 2), "properties": {"Zoning": "R-5"}},
        ],
    }
    assert build_zoning_overlay_geojson(parcels, zoning)["features"] == []


def test_build_script_writes_file(tmp_path: Path) -> None:
    parcels_path = tmp_path / "parcels.geojson"
    zoning_path = tmp_path / "zoning.geojson"
    out_path = tmp_path / "overlay.geojson"
    parcels = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0.5, 0.5, 0.1),
                "properties": {"APN": "X1", "COUNTY_FIPS": "24510"},
            }
        ],
    }
    zoning = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0, 0, 2),
                "properties": {"Zoning": "R-5"},
            }
        ],
    }
    parcels_path.write_text(json.dumps(parcels))
    zoning_path.write_text(json.dumps(zoning))
    overlay = build_zoning_overlay_geojson(
        json.loads(parcels_path.read_text()),
        json.loads(zoning_path.read_text()),
    )
    out_path.write_text(json.dumps(overlay))
    assert len(json.loads(out_path.read_text())["features"]) == 1
