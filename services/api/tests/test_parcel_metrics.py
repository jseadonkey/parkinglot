from __future__ import annotations

from shapely.geometry import Polygon

from parking_ingestion.parcel_metrics import (
    geodesic_footprint_sqft,
    haversine_m,
    min_distance_to_generators_m,
)


def test_haversine_seattle_to_bellevue_order_of_magnitude() -> None:
    # Rough check: Seattle core to Bellevue CBD is ~10 km across Lake Washington
    d = haversine_m(47.6062, -122.3321, 47.6101, -122.2015)
    assert 8000 < d < 15000


def test_min_distance_to_generators() -> None:
    gens = [{"name": "A", "lat": 0.0, "lon": 0.0}, {"name": "B", "lat": 1.0, "lon": 0.0}]
    d = min_distance_to_generators_m(0.5, 0.0, gens)
    assert d is not None
    assert d < haversine_m(0.0, 0.0, 1.0, 0.0)


def test_geodesic_footprint_sqft_small_polygon() -> None:
    # ~111m per degree latitude — 0.001 deg square is tiny but non-zero area
    poly = Polygon([(0, 0), (0.001, 0), (0.001, 0.001), (0, 0.001), (0, 0)])
    sqft = geodesic_footprint_sqft(poly)
    assert sqft is not None
    assert 100 < sqft < 500_000
