from __future__ import annotations

from pathlib import Path

from app.wa_phase_b_rollout import load_phase_b_config
from parking_ingestion.baltimore_zoning_overlay import build_zoning_overlay_geojson
from parking_ingestion.wa_county_zoning_build import (
    DEFAULT_ARCGIS_ZONING_SOURCES,
    build_county_zoning_overlay_geojson,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _square(x0: float, y0: float, size: float = 1.0) -> dict:
    x1, y1 = x0 + size, y0 + size
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def test_spatial_overlay_uses_watech_parcel_id_as_apn() -> None:
    parcels = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0.5, 0.5, 0.1),
                "properties": {"PARCEL_ID_NR": "033-12345", "COUNTY_FIPS": "53033"},
            }
        ],
    }
    zoning = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _square(0, 0, 2), "properties": {"CURRZONE": "R-6"}},
        ],
    }

    overlay = build_zoning_overlay_geojson(
        parcels,
        zoning,
        county_fips="53033",
        zoning_field="CURRZONE",
        zoning_jurisdiction="king_unincorporated",
    )

    assert len(overlay["features"]) == 1
    props = overlay["features"][0]["properties"]
    assert props["APN"] == "033-12345"
    assert props["ZONING"] == "R-6"
    assert props["ZONING_JURISDICTION"] == "king_unincorporated"


def test_config_registers_priority_wa_zoning_builders() -> None:
    config = load_phase_b_config(REPO_ROOT / "config/wa_phase_b_rollout.yaml")

    for county_fips in ("53033", "53053", "53061", "53035", "53067"):
        settings = config["counties"][county_fips]
        assert settings["auto_build_overlay"] is True
        assert settings["overlay_path"].startswith("/app/data/")
        assert settings["zoning_sources"][0]["layer_url"].startswith("https://")
        assert settings["zoning_sources"][0]["zoning_field"]
        assert settings["zoning_sources"][0]["zoning_jurisdiction"]


def test_default_source_registry_covers_priority_wa_counties() -> None:
    assert set(DEFAULT_ARCGIS_ZONING_SOURCES) >= {"53033", "53053", "53061", "53035", "53067"}


def test_generic_wa_county_builder_fetches_and_joins(monkeypatch, tmp_path: Path) -> None:
    parcels = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": _square(0.5, 0.5, 0.1),
                "properties": {"PARCEL_ID_NR": "053-1", "COUNTY_FIPS": "53053"},
            },
            {
                "type": "Feature",
                "geometry": _square(4, 4, 0.1),
                "properties": {"PARCEL_ID_NR": "053-2", "COUNTY_FIPS": "53053"},
            },
        ],
    }
    zoning = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _square(0, 0, 2), "properties": {"ZONING": "AC"}},
        ],
    }

    monkeypatch.setattr(
        "parking_ingestion.watech_parcels.fetch_county_geojson",
        lambda county_fips: parcels,
    )
    monkeypatch.setattr(
        "parking_ingestion.benton_zoning.fetch_zoning_geojson",
        lambda **_kwargs: zoning,
    )

    overlay = build_county_zoning_overlay_geojson(
        "53053",
        cache_dir=tmp_path,
        zoning_sources=[
            {
                "source_id": "pierce_county_zoning",
                "label": "Pierce County zoning",
                "layer_url": "https://example.test/zoning/FeatureServer/0",
                "zoning_field": "ZONING",
                "zoning_jurisdiction": "pierce_county",
            },
        ],
    )

    assert len(overlay["features"]) == 1
    props = overlay["features"][0]["properties"]
    assert props["APN"] == "053-1"
    assert props["ZONING"] == "AC"
    assert props["COUNTY_FIPS"] == "53053"
    assert props["ZONING_JURISDICTION"] == "pierce_county"
    assert props["ZONING_MATCH_METHOD"] == "pierce_county_zoning_spatial"
