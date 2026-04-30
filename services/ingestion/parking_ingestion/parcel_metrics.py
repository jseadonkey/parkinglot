"""Geometry- and pilot-derived metrics for parcel ingest (WGS84)."""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry.base import BaseGeometry

_SQFT_PER_SQM = 10.76391041671


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (WGS84 sphere approximation)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def geodesic_footprint_sqft(geom: BaseGeometry) -> float | None:
    """Polygon / MultiPolygon area on the ellipsoid → square feet."""
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    try:
        from pyproj import Geod
    except ImportError:
        return None
    geod = Geod(ellps="WGS84")
    try:
        area_m2, _perim_m = geod.geometry_area_perimeter(geom)
    except Exception:
        return None
    return abs(float(area_m2)) * _SQFT_PER_SQM


def _generator_latlons(generators: list[dict[str, Any]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for g in generators:
        lat = g.get("lat") if "lat" in g else g.get("latitude")
        lon = g.get("lon") if "lon" in g else g.get("longitude") or g.get("lng")
        if lat is None or lon is None:
            continue
        try:
            out.append((float(lat), float(lon)))
        except (TypeError, ValueError):
            continue
    return out


def min_distance_to_generators_m(
    lat: float,
    lon: float,
    generators: list[dict[str, Any]],
) -> float | None:
    """Shortest surface distance from a point to any ``{lat, lon}`` demand POI in meters."""
    pts = _generator_latlons(generators)
    if not pts:
        return None
    return min(haversine_m(lat, lon, plat, plon) for plat, plon in pts)
