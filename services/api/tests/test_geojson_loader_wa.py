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
