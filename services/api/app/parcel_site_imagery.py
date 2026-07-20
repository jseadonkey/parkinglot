"""Parcel site imagery: Street View when configured, else aerial satellite."""

from __future__ import annotations

import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Literal

from app.config import get_settings

logger = logging.getLogger(__name__)

ImagerySource = Literal["street", "satellite", "auto"]

_ESRI_EXPORT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
_STREET_VIEW_META = "https://maps.googleapis.com/maps/api/streetview/metadata"
_STREET_VIEW_STATIC = "https://maps.googleapis.com/maps/api/streetview"
_USER_AGENT = "parkinglot-operator-console/1.0 (parcel site imagery)"


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


def satellite_map_url(lat: float, lon: float, *, zoom: int = 18) -> str:
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


def _bbox_for_parcel(lat: float, lon: float, *, half_span_deg: float) -> str:
    return f"{lon - half_span_deg},{lat - half_span_deg},{lon + half_span_deg},{lat + half_span_deg}"


def fetch_satellite_image(
    lat: float,
    lon: float,
    *,
    width: int = 480,
    height: int = 360,
) -> SiteImage | None:
    """Esri World Imagery export centered on the parcel centroid (no API key)."""
    # ~120–180m half-span at mid-latitudes — lot-level context for parking screening.
    half = max(0.0006, min(0.0025, 0.0012 / max(0.35, math.cos(math.radians(lat)))))
    params = urllib.parse.urlencode(
        {
            "bbox": _bbox_for_parcel(lat, lon, half_span_deg=half),
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{width},{height}",
            "format": "jpg",
            "f": "image",
        }
    )
    got = _http_get_bytes(f"{_ESRI_EXPORT}?{params}")
    if not got or len(got[0]) < 500:
        return None
    body, ctype = got
    if "image" not in ctype:
        ctype = "image/jpeg"
    return SiteImage(body=body, content_type=ctype, source="satellite", lat=lat, lon=lon)


def _google_maps_api_key() -> str:
    return (get_settings().google_maps_api_key or "").strip()


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
        import json

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
) -> SiteImage | None:
    width = max(120, min(int(width), 1280))
    height = max(90, min(int(height), 960))
    if source in ("street", "auto"):
        street = fetch_street_view_image(lat, lon, width=width, height=height)
        if street is not None:
            return street
        if source == "street":
            return None
    return fetch_satellite_image(lat, lon, width=width, height=height)
