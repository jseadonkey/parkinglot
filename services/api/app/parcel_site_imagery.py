"""Parcel site imagery: Street View when configured, else aerial with lot outline."""

from __future__ import annotations

import io
import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

from app.config import get_settings

logger = logging.getLogger(__name__)

ImagerySource = Literal["street", "satellite", "auto"]

_ESRI_EXPORT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
_STREET_VIEW_META = "https://maps.googleapis.com/maps/api/streetview/metadata"
_STREET_VIEW_STATIC = "https://maps.googleapis.com/maps/api/streetview"
_USER_AGENT = "parkinglot-operator-console/1.0 (parcel site imagery)"

# Lot outline styling (high contrast on aerial imagery).
_OUTLINE_RGBA = (255, 214, 32, 255)
_FILL_RGBA = (255, 214, 32, 55)
_OUTLINE_WIDTH = 4


@dataclass(frozen=True)
class SiteImage:
    body: bytes
    content_type: str
    source: Literal["street", "satellite"]
    lat: float
    lon: float


def street_view_url(lat: float, lon: float) -> str:
    """Deep link into Google Street View (no API key)."""
    return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat:.6f},{lon:.6f}"


def satellite_map_url(lat: float, lon: float, *, zoom: int = 19) -> str:
    return f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},{zoom}z/data=!3m1!1e3"


def _http_get_bytes(url: str, *, timeout_s: float = 20.0) -> tuple[bytes, str] | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            ctype = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
            return resp.read(), ctype
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("site imagery fetch failed: %s", exc)
        return None


def _google_maps_api_key() -> str:
    return (get_settings().google_maps_api_key or "").strip()


def _rings_lonlat(geom: Any) -> list[list[tuple[float, float]]]:
    """Exterior rings as (lon, lat) lists from a Shapely geometry."""
    if geom is None or geom.is_empty:
        return []
    rings: list[list[tuple[float, float]]] = []
    geoms = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for g in geoms:
        if g.geom_type != "Polygon" or g.exterior is None:
            continue
        coords = [(float(x), float(y)) for x, y in g.exterior.coords]
        if len(coords) >= 3:
            rings.append(coords)
    return rings


def _padded_bbox(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    *,
    pad_frac: float = 0.22,
    min_pad_m: float = 12.0,
    min_span_m: float = 52.0,
) -> tuple[float, float, float, float]:
    """Expand footprint bbox with padding and a minimum ground span (readable thumbs)."""
    mid_lat = (miny + maxy) / 2.0
    m_per_deg_lat = 110_540.0
    m_per_deg_lon = 111_320.0 * max(0.2, math.cos(math.radians(mid_lat)))
    pad_x = max((maxx - minx) * pad_frac, min_pad_m / m_per_deg_lon)
    pad_y = max((maxy - miny) * pad_frac, min_pad_m / m_per_deg_lat)
    minx, miny, maxx, maxy = minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y
    # Skinny slivers need a floor span so the lot isn't a 1px hairline after letterbox.
    need_x = min_span_m / m_per_deg_lon
    need_y = min_span_m / m_per_deg_lat
    if (maxx - minx) < need_x:
        cx = (minx + maxx) / 2.0
        minx, maxx = cx - need_x / 2.0, cx + need_x / 2.0
    if (maxy - miny) < need_y:
        cy = (miny + maxy) / 2.0
        miny, maxy = cy - need_y / 2.0, cy + need_y / 2.0
    return minx, miny, maxx, maxy


def _match_aspect(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    *,
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    """Grow bbox so geographic aspect matches the image (avoids stretch distortion)."""
    bw = max(maxx - minx, 1e-9)
    bh = max(maxy - miny, 1e-9)
    target = width / max(height, 1)
    current = bw / bh
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    if current < target:
        # too tall — widen
        bw = bh * target
    else:
        # too wide — heighten
        bh = bw / target
    return cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2


def footprint_image_bbox(
    geom: Any,
    *,
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    """Return (min_lon, min_lat, max_lon, max_lat) fitted to the lot + padding."""
    if geom is None or geom.is_empty:
        return None
    minx, miny, maxx, maxy = geom.bounds
    padded = _padded_bbox(minx, miny, maxx, maxy)
    return _match_aspect(*padded, width=width, height=height)


def _lonlat_to_px(
    lon: float,
    lat: float,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[float, float]:
    minx, miny, maxx, maxy = bbox
    x = (lon - minx) / max(maxx - minx, 1e-12) * (width - 1)
    y = (maxy - lat) / max(maxy - miny, 1e-12) * (height - 1)
    return x, y


def overlay_lot_outline(
    image_bytes: bytes,
    geom: Any,
    bbox: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
) -> bytes:
    """Draw the parcel footprint on an aerial JPEG (requires Pillow)."""
    from PIL import Image, ImageDraw

    rings = _rings_lonlat(geom)
    if not rings:
        return image_bytes
    with Image.open(io.BytesIO(image_bytes)) as base:
        img = base.convert("RGBA")
        if img.size != (width, height):
            img = img.resize((width, height), Image.Resampling.BILINEAR)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        for ring in rings:
            pts = [_lonlat_to_px(lon, lat, bbox, width, height) for lon, lat in ring]
            if len(pts) < 3:
                continue
            draw.polygon(pts, fill=_FILL_RGBA)
            draw.line(pts + [pts[0]], fill=_OUTLINE_RGBA, width=_OUTLINE_WIDTH, joint="curve")
        composed = Image.alpha_composite(img, overlay).convert("RGB")
        out = io.BytesIO()
        composed.save(out, format="JPEG", quality=86, optimize=True)
        return out.getvalue()


def fetch_satellite_image(
    lat: float,
    lon: float,
    *,
    width: int = 480,
    height: int = 360,
    footprint: Any | None = None,
) -> SiteImage | None:
    """Esri World Imagery centered on the lot (tight bbox + outline when footprint given)."""
    from PIL import Image

    bbox: tuple[float, float, float, float]
    fetch_w, fetch_h = width, height
    letterbox = False
    if footprint is not None and not getattr(footprint, "is_empty", True):
        fitted = footprint_image_bbox(footprint, width=width, height=height)
        if fitted is None:
            return None
        # Geographic bbox stays tight to the lot (no aspect stretch). Request a
        # matching pixel size, then letterbox onto the UI canvas so skinny lots
        # don't get drowned in side context.
        minx, miny, maxx, maxy = footprint.bounds
        bbox = _padded_bbox(minx, miny, maxx, maxy)
        lat = (bbox[1] + bbox[3]) / 2.0
        lon = (bbox[0] + bbox[2]) / 2.0
        mid_lat = lat
        m_per_deg_lat = 110_540.0
        m_per_deg_lon = 111_320.0 * max(0.2, math.cos(math.radians(mid_lat)))
        geo_w_m = max((bbox[2] - bbox[0]) * m_per_deg_lon, 1.0)
        geo_h_m = max((bbox[3] - bbox[1]) * m_per_deg_lat, 1.0)
        geo_aspect = geo_w_m / geo_h_m
        canvas_aspect = width / max(height, 1)
        if geo_aspect >= canvas_aspect:
            fetch_w = width
            fetch_h = max(32, int(round(width / geo_aspect)))
        else:
            fetch_h = height
            fetch_w = max(32, int(round(height * geo_aspect)))
        # Never fetch a tiny strip — upscale pixel size then letterbox (keeps outline readable).
        min_px = 96
        if fetch_w < min_px:
            scale = min_px / max(fetch_w, 1)
            fetch_w = min_px
            fetch_h = min(height, max(min_px, int(round(fetch_h * scale))))
        if fetch_h < min_px:
            scale = min_px / max(fetch_h, 1)
            fetch_h = min_px
            fetch_w = min(width, max(min_px, int(round(fetch_w * scale))))
        letterbox = fetch_w != width or fetch_h != height
    else:
        half = max(0.00035, min(0.0012, 0.00055 / max(0.35, math.cos(math.radians(lat)))))
        bbox = (lon - half, lat - half, lon + half, lat + half)
        bbox = _match_aspect(*bbox, width=width, height=height)

    params = urllib.parse.urlencode(
        {
            "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{fetch_w},{fetch_h}",
            "format": "jpg",
            "f": "image",
        }
    )
    got = _http_get_bytes(f"{_ESRI_EXPORT}?{params}")
    if not got or len(got[0]) < 500:
        return None
    body, ctype = got
    if footprint is not None and not getattr(footprint, "is_empty", True):
        try:
            body = overlay_lot_outline(body, footprint, bbox, width=fetch_w, height=fetch_h)
            ctype = "image/jpeg"
        except Exception as exc:
            logger.info("lot outline overlay failed: %s", exc)
    if letterbox:
        try:
            with Image.open(io.BytesIO(body)) as tile:
                canvas = Image.new("RGB", (width, height), color=(12, 16, 22))
                tile_rgb = tile.convert("RGB")
                if tile_rgb.size != (fetch_w, fetch_h):
                    tile_rgb = tile_rgb.resize((fetch_w, fetch_h), Image.Resampling.BILINEAR)
                ox = (width - fetch_w) // 2
                oy = (height - fetch_h) // 2
                canvas.paste(tile_rgb, (ox, oy))
                out = io.BytesIO()
                canvas.save(out, format="JPEG", quality=86, optimize=True)
                body = out.getvalue()
                ctype = "image/jpeg"
        except Exception as exc:
            logger.info("letterbox compose failed: %s", exc)
    if "image" not in (ctype or ""):
        ctype = "image/jpeg"
    return SiteImage(body=body, content_type=ctype, source="satellite", lat=lat, lon=lon)


def fetch_street_view_image(
    lat: float,
    lon: float,
    *,
    width: int = 480,
    height: int = 360,
) -> SiteImage | None:
    """Google Street View Static image when GOOGLE_MAPS_API_KEY is set."""
    key = _google_maps_api_key()
    if not key:
        return None
    meta_q = urllib.parse.urlencode({"location": f"{lat:.6f},{lon:.6f}", "key": key})
    meta = _http_get_bytes(f"{_STREET_VIEW_META}?{meta_q}", timeout_s=12.0)
    if not meta:
        return None
    try:
        status = str(json.loads(meta[0].decode("utf-8", errors="replace")).get("status") or "")
    except Exception:
        return None
    if status != "OK":
        return None
    img_q = urllib.parse.urlencode(
        {
            "location": f"{lat:.6f},{lon:.6f}",
            "size": f"{width}x{height}",
            "fov": "90",
            "pitch": "0",
            "source": "outdoor",
            "key": key,
        }
    )
    got = _http_get_bytes(f"{_STREET_VIEW_STATIC}?{img_q}")
    if not got or len(got[0]) < 500:
        return None
    body, ctype = got
    if "image" not in ctype:
        ctype = "image/jpeg"
    return SiteImage(body=body, content_type=ctype, source="street", lat=lat, lon=lon)


def fetch_site_image(
    lat: float,
    lon: float,
    *,
    source: ImagerySource = "auto",
    width: int = 480,
    height: int = 360,
    footprint: Any | None = None,
) -> SiteImage | None:
    width = max(120, min(int(width), 1280))
    height = max(90, min(int(height), 960))
    # Prefer aerial+lot outline when we have a footprint — Street View can't show lot lines.
    if footprint is not None and source in ("auto", "satellite"):
        sat = fetch_satellite_image(lat, lon, width=width, height=height, footprint=footprint)
        if sat is not None:
            return sat
        if source == "satellite":
            return None
    if source in ("street", "auto"):
        street = fetch_street_view_image(lat, lon, width=width, height=height)
        if street is not None:
            return street
        if source == "street":
            return None
    return fetch_satellite_image(lat, lon, width=width, height=height, footprint=footprint)
