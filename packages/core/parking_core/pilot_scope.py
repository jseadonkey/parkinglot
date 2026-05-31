"""Geographic pilot scope — Kent city + King County unincorporated (excludes other cities)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep


def discover_repo_root(*, pilot_config_path: str | Path | None = None) -> Path:
    """Repo root for resolving ``data/...`` paths (Docker ``/app``, dev checkout, or env override)."""
    for env_key in ("PARKINGLOT_REPO_ROOT", "REPO_ROOT"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            return Path(raw)

    candidates: list[Path] = []
    if pilot_config_path is not None:
        pp = Path(pilot_config_path)
        if pp.is_file():
            candidates.append(pp.resolve().parent.parent)

    env_pilot = os.environ.get("PILOT_CONFIG_PATH", "").strip()
    if env_pilot:
        pp = Path(env_pilot)
        if pp.is_file():
            candidates.append(pp.resolve().parent.parent)

    if Path("/app/config/pilot.yaml").is_file():
        candidates.append(Path("/app"))

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "boundaries").is_dir():
            candidates.append(parent)

    for root in candidates:
        if (root / "data").is_dir():
            return root

    return here.parents[3]


def _repo_relative(path: str | Path, *, repo_root: Path | None = None, pilot_config_path: str | Path | None = None) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p

    root = repo_root or discover_repo_root(pilot_config_path=pilot_config_path)
    candidate = root / p
    if candidate.is_file():
        return candidate

    # Docker compose mounts repo data at /app/data (pilot YAML uses data/... relative paths).
    if str(p).startswith("data/"):
        docker = Path("/app") / p
        if docker.is_file():
            return docker

    return candidate


def _load_feature_collection(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _union_named_features(fc: dict[str, Any], *, name_filter: str | None = None) -> Any:
    polys = []
    for feat in fc.get("features") or []:
        geom = feat.get("geometry")
        if not geom:
            continue
        props = feat.get("properties") or {}
        if name_filter:
            name = str(props.get("name") or props.get("BASENAME") or props.get("NAME") or "").lower()
            if name_filter not in name:
                continue
        polys.append(shape(geom))
    if not polys:
        raise ValueError(f"no matching polygons in {path}")
    return unary_union(polys)


@lru_cache(maxsize=8)
def _prepared_union(path_str: str, name_filter: str | None) -> Any:
    path = Path(path_str)
    fc = _load_feature_collection(path)
    geom = _union_named_features(fc, name_filter=name_filter)
    return prep(geom)


def parcel_centroid_in_prepared(pt: Point, prepared_geom: Any) -> bool:
    return bool(prepared_geom.contains(pt) or prepared_geom.intersects(pt))


def classify_king_kent_scope(
    lon: float,
    lat: float,
    *,
    kent_boundary_geojson: str | Path,
    excluded_incorporated_geojson: str | Path,
    repo_root: Path | None = None,
    pilot_config_path: str | Path | None = None,
) -> bool:
    """True when centroid is in Kent city or King County unincorporated (not another city)."""
    kent_path = _repo_relative(
        kent_boundary_geojson,
        repo_root=repo_root,
        pilot_config_path=pilot_config_path,
    )
    excl_path = _repo_relative(
        excluded_incorporated_geojson,
        repo_root=repo_root,
        pilot_config_path=pilot_config_path,
    )
    pt = Point(lon, lat)
    kent = _prepared_union(str(kent_path.resolve()), "kent")
    if parcel_centroid_in_prepared(pt, kent):
        return True
    excluded = _prepared_union(str(excl_path.resolve()), None)
    if parcel_centroid_in_prepared(pt, excluded):
        return False
    return True


def classify_from_in_scope_config(
    lon: float,
    lat: float,
    in_scope: Any,
    *,
    repo_root: Path | None = None,
    pilot_config_path: str | Path | None = None,
) -> bool:
    if in_scope is None:
        return True
    kent = getattr(in_scope, "kent_city_boundary_geojson", None) or (
        in_scope.get("kent_city_boundary_geojson") if isinstance(in_scope, dict) else None
    )
    excl = getattr(in_scope, "excluded_incorporated_places_geojson", None) or (
        in_scope.get("excluded_incorporated_places_geojson") if isinstance(in_scope, dict) else None
    )
    if not kent or not excl:
        return True
    return classify_king_kent_scope(
        lon,
        lat,
        kent_boundary_geojson=kent,
        excluded_incorporated_geojson=excl,
        repo_root=repo_root,
        pilot_config_path=pilot_config_path,
    )
