from __future__ import annotations

from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict


def test_loader_maps_pin_and_acres_to_sqft() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"PIN": "KC-001", "COUNTY_FIPS": "53033", "CALC_ACRES": 1.0},
            }
        ],
    }
    rows = list(iter_parcels_from_geojson_dict(fc))
    assert len(rows) == 1
    attrs, _geom = rows[0]
    assert attrs["apn"] == "KC-001"
    assert attrs["county_fips"] == "53033"
    assert attrs["lot_sqft"] == 43560.0


def test_loader_accepts_classic_apn_keys() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {
                    "APN": "123-456-789",
                    "COUNTY_FIPS": "53033",
                    "LOT_SQFT": 6000.0,
                    "ZONING_ALLOWS_SURFACE_PARKING": True,
                },
            }
        ],
    }
    attrs, _ = list(iter_parcels_from_geojson_dict(fc))[0]
    assert attrs["apn"] == "123-456-789"
    assert attrs["lot_sqft"] == 6000.0
    assert attrs["zoning_allows_surface_parking"] is True


def test_loader_tri_state_missing_zoning_allow_uses_rules_default() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {
                    "APN": "999",
                    "COUNTY_FIPS": "53033",
                    "ZONING": "UNMAPPED-ZONE",
                    "ZONING_JURISDICTION": "kent_city",
                },
            }
        ],
    }
    attrs, _ = list(iter_parcels_from_geojson_dict(fc))[0]
    assert attrs["zoning_allows_surface_parking"] is False


def test_loader_skips_null_and_invalid_geometry() -> None:
    """WaTech pages sometimes include features with geometry: null — skip, don't crash."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": None,
                "properties": {"APN": "bad-null", "COUNTY_FIPS": "53075"},
            },
            {
                "type": "Feature",
                "geometry": {},
                "properties": {"APN": "bad-empty", "COUNTY_FIPS": "53075"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"APN": "good", "COUNTY_FIPS": "53075", "LOT_SQFT": 1000.0},
            },
        ],
    }
    rows = list(iter_parcels_from_geojson_dict(fc))
    assert len(rows) == 1
    assert rows[0][0]["apn"] == "good"
