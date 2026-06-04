from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from parking_core.geography_registry import GeographyAgent, GeographyRegistry, load_geography_registry
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    marker = Path("config") / "geography_registry.yaml"
    for parent in (here.parent, *here.parents):
        if (parent / marker).is_file():
            return parent
    return here.parents[3]


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    root_candidate = _repo_root() / candidate
    if root_candidate.is_file():
        return root_candidate
    app_candidate = Path("/app") / candidate
    if app_candidate.is_file():
        return app_candidate
    return root_candidate


@lru_cache(maxsize=64)
def _load_boundary_geometries(path: str) -> tuple[BaseGeometry, ...]:
    boundary_path = _resolve_path(path)
    if not boundary_path.is_file():
        return ()
    raw = json.loads(boundary_path.read_text(encoding="utf-8"))
    if raw.get("type") == "FeatureCollection":
        features = raw.get("features") or []
    elif raw.get("type") == "Feature":
        features = [raw]
    else:
        features = [{"geometry": raw}]

    geometries: list[BaseGeometry] = []
    for feature in features:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not geometry:
            continue
        geom = shape(geometry)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if not geom.is_empty:
            geometries.append(geom)
    return tuple(geometries)


def _representative_test_geometry(geom: BaseGeometry) -> BaseGeometry:
    if geom.geom_type == "Point":
        return geom
    return geom.representative_point()


def _matching_boundary_jurisdiction(geographies: list[GeographyAgent], geom: BaseGeometry) -> str | None:
    test_geom = _representative_test_geometry(geom)
    for geography in geographies:
        if not geography.boundary_path or not geography.jurisdiction_key:
            continue
        for boundary in _load_boundary_geometries(geography.boundary_path):
            if boundary.covers(test_geom) or boundary.intersects(geom):
                return geography.jurisdiction_key
    return None


def resolve_zoning_jurisdiction(
    county_fips: str,
    explicit_jurisdiction: str | None,
    *,
    geom: BaseGeometry | None = None,
    registry: GeographyRegistry | None = None,
) -> str | None:
    """Resolve zoning jurisdiction from explicit props, city boundaries, then county default."""

    if explicit_jurisdiction is not None and str(explicit_jurisdiction).strip():
        return str(explicit_jurisdiction).strip().lower()

    cf = (county_fips or "").strip()
    if not cf:
        return None

    active_registry = registry or load_geography_registry()
    if geom is not None:
        boundary_geographies = active_registry.boundary_geographies_for_county(cf)
        match = _matching_boundary_jurisdiction(boundary_geographies, geom)
        if match:
            return match

    return active_registry.default_jurisdiction_for_county(cf)


def resolve_feature_zoning_jurisdiction(
    properties: dict[str, Any],
    geom: BaseGeometry,
    *,
    registry: GeographyRegistry | None = None,
) -> str | None:
    county = str(
        properties.get("COUNTY_FIPS")
        or properties.get("county_fips")
        or properties.get("COUNTYFP")
        or properties.get("COUNTY_FIP")
        or ""
    ).strip()
    explicit = properties.get("ZONING_JURISDICTION") or properties.get("zoning_jurisdiction")
    return resolve_zoning_jurisdiction(county, str(explicit).strip() if explicit is not None else None, geom=geom, registry=registry)
