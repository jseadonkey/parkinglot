"""In-memory zoning index for Kent city + King unincorporated layers (centroid lookup)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import Point, shape
from shapely.strtree import STRtree


def _fetch_esri_query_pages(layer_base_url: str, *, page_size: int = 2000) -> dict[str, Any]:
    base = layer_base_url.rstrip("/")
    if not base.lower().endswith("/query"):
        base = f"{base}/query"

    all_features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "f": "geojson",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "resultRecordCount": str(page_size),
            "resultOffset": str(offset),
        }
        url = f"{base}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "parkinglot-prescreen/1.0"})
        try:
            with urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} fetching {base}: {e.reason}") from e
        except URLError as e:
            raise RuntimeError(f"network error fetching {base}: {e}") from e

        chunk = json.loads(raw)
        feats = chunk.get("features") or []
        if not feats:
            break
        all_features.extend(feats)
        if len(feats) < page_size:
            break
        offset += page_size

    return {"type": "FeatureCollection", "features": all_features}


def _load_geojson_path(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_zoning_source(src: str) -> dict[str, Any]:
    s = src.strip()
    if s.lower().startswith(("http://", "https://")):
        return _fetch_esri_query_pages(s)
    p = Path(s)
    if not p.is_file():
        raise FileNotFoundError(f"zoning source not found: {p}")
    return _load_geojson_path(p)


def _zone_value(props: dict[str, Any], field: str) -> str | None:
    if field not in props or props[field] is None:
        return None
    s = str(props[field]).strip()
    return s if s else None


class PilotZoningLookup:
    """Point → zone code for Kent city or King unincorporated zoning polygons."""

    def __init__(
        self,
        *,
        kent_source: str,
        king_source: str,
        kent_zone_field: str = "Short_Name",
        king_zone_field: str = "CURRZONE",
    ) -> None:
        kent_fc = _load_zoning_source(kent_source)
        king_fc = _load_zoning_source(king_source)

        self._kent_geoms: list[Any] = []
        self._kent_props: list[dict[str, Any]] = []
        self._king_geoms: list[Any] = []
        self._king_props: list[dict[str, Any]] = []

        for feat in kent_fc.get("features") or []:
            g = feat.get("geometry")
            if g:
                self._kent_geoms.append(shape(g))
                self._kent_props.append(dict(feat.get("properties") or {}))

        for feat in king_fc.get("features") or []:
            g = feat.get("geometry")
            if g:
                self._king_geoms.append(shape(g))
                self._king_props.append(dict(feat.get("properties") or {}))

        self._kent_field = kent_zone_field
        self._king_field = king_zone_field
        self._kent_tree = STRtree(self._kent_geoms) if self._kent_geoms else None
        self._king_tree = STRtree(self._king_geoms) if self._king_geoms else None

    @classmethod
    def from_env(cls) -> PilotZoningLookup | None:
        kent = os.environ.get("KENT_ZONING", "").strip()
        king = os.environ.get("KING_ZONING", "").strip()
        if not kent or not king:
            return None
        return cls(
            kent_source=kent,
            king_source=king,
            kent_zone_field=os.environ.get("KENT_ZONE_FIELD", "Short_Name"),
            king_zone_field=os.environ.get("KING_ZONE_FIELD", "CURRZONE"),
        )

    def _pick(
        self,
        pt: Point,
        tree: STRtree | None,
        geoms: list[Any],
        prop_rows: list[dict[str, Any]],
        zone_field: str,
    ) -> str | None:
        from shapely import prepared

        if tree is None:
            return None
        cand = list(tree.query(pt, predicate="within"))
        if not cand:
            cand = list(tree.query(pt, predicate="intersects"))
        if not cand:
            return None

        best: tuple[float, str | None] | None = None
        for i in cand:
            g = geoms[i]
            pr = prepared.prep(g)
            if not pr.contains(pt) and not pr.intersects(pt):
                continue
            z = _zone_value(prop_rows[i], zone_field)
            if z is None:
                continue
            try:
                area = float(g.area)
            except Exception:
                area = 0.0
            if best is None or area < best[0]:
                best = (area, z)
        return best[1] if best else None

    def zone_at(self, lon: float, lat: float, jurisdiction: str) -> str | None:
        pt = Point(lon, lat)
        if jurisdiction == "kent_city":
            return self._pick(pt, self._kent_tree, self._kent_geoms, self._kent_props, self._kent_field)
        return self._pick(pt, self._king_tree, self._king_geoms, self._king_props, self._king_field)
