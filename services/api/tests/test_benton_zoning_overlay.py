"""Tests for Benton County zoning fetch + overlay helpers."""

from __future__ import annotations

from parking_ingestion.benton_zoning import normalize_benton_county_tax_id, situs_city_from_props
from parking_ingestion.benton_zoning_overlay import (
    apply_kennewick_attribute_join,
    build_benton_zoning_overlay_geojson,
)


def test_normalize_benton_county_tax_id_strips_prefix_and_dashes():
    assert normalize_benton_county_tax_id("005-104893100000004") == "104893100000004"
    assert normalize_benton_county_tax_id("104893100000004") == "104893100000004"
    assert normalize_benton_county_tax_id("") == ""


def test_situs_city_from_props_reads_city_field():
    assert situs_city_from_props({"SITUS_CITY_NM": "Kennewick"}) == "KENNEWICK"
    assert situs_city_from_props({"SITUS_ADDRESS": "123 MAIN\nPASCO, WA 99301"}) == "PASCO"


def test_kennewick_attribute_join_matches_tax_id():
    parcels_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-119.1, 46.2]},
                "properties": {"PARCEL_ID_NR": "005-104893100000004"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-119.2, 46.3]},
                "properties": {"PARCEL_ID_NR": "005-999999999999999"},
            },
        ],
    }
    matched, unmatched = apply_kennewick_attribute_join(
        parcels_fc,
        kennewick_zoning_by_tax_id={"104893100000004": "RL"},
    )
    assert len(matched) == 1
    assert matched[0]["properties"]["ZONING"] == "RL"
    assert matched[0]["properties"]["ZONING_JURISDICTION"] == "kennewick_city"
    assert len(unmatched) == 1


def test_build_overlay_geojson_kennewick_only():
    parcels_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-119.1, 46.2]},
                "properties": {"PARCEL_ID_NR": "005-104893100000004"},
            }
        ],
    }
    overlay = build_benton_zoning_overlay_geojson(
        parcels_fc,
        kennewick_zoning_by_tax_id={"104893100000004": "RL"},
    )
    assert len(overlay["features"]) == 1
    props = overlay["features"][0]["properties"]
    assert props["APN"] == "005-104893100000004"
    assert props["ZONING"] == "RL"
