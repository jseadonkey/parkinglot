"""Lot surface hints: paved vs vegetated, plus active-parking detection.

Operators want downtown **vacant, paved (or mostly paved)** pads that are
**not already operating parking**. Assessor Present Use is a fast prior;
aerial pixels refine surface and flag lots that are full of cars.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

logger = logging.getLogger(__name__)

SurfaceKind = Literal["paved", "vegetated", "mixed", "unknown"]

# King vacant commercial / industrial — usually paved or hard-surface pads.
_PAVED_LIKELY_LANDUSE = frozenset({"309", "316"})
# King vacant residential — usually grass / dirt.
_VEGETATED_LIKELY_LANDUSE = frozenset({"300", "301", "299"})

# Aerial: cars on asphalt (operating lot) vs empty pad.
_ACTIVE_PARKING_MIN_PAVED = 0.28
_ACTIVE_PARKING_MIN_VEHICLE = 0.14
# White/silver car roofs and stall paint often look near-pavement gray.
_ACTIVE_PARKING_MIN_BRIGHT = 0.08
_ACTIVE_PARKING_BRIGHT_PAVED = 0.55
# "Mostly paved" for operator preference (includes mixed with enough asphalt).
_MOSTLY_PAVED_MIN = 0.32


@dataclass(frozen=True)
class LotSurface:
    kind: SurfaceKind
    paved_fraction: float | None = None
    vegetated_fraction: float | None = None
    vehicle_fraction: float | None = None
    looks_like_active_parking: bool = False
    source: Literal["assessor", "aerial", "unknown"] = "unknown"

    @property
    def is_mostly_paved(self) -> bool:
        if self.kind == "paved":
            return True
        if self.kind == "mixed" and (self.paved_fraction or 0) >= _MOSTLY_PAVED_MIN:
            return True
        return False


def _present_use_tail(code: str) -> str:
    text = code.strip()
    if "-" in text:
        return text.rsplit("-", 1)[-1].strip()
    return text


def assessor_surface_hint(raw_properties: dict[str, Any] | None) -> LotSurface:
    """Fast prior from King Present Use / land-use text (no imagery)."""
    props = raw_properties or {}
    for key in ("LANDUSE_CD", "landuse_cd", "ORIG_LANDUSE_CD", "orig_landuse_cd"):
        raw = props.get(key)
        if raw is None or not str(raw).strip():
            continue
        tail = _present_use_tail(str(raw))
        if tail in _PAVED_LIKELY_LANDUSE:
            return LotSurface(kind="paved", source="assessor")
        if tail in _VEGETATED_LIKELY_LANDUSE:
            return LotSurface(kind="vegetated", source="assessor")
    blob = " ".join(str(props.get(k) or "") for k in ("LANDUSE", "LANDUSE_CD", "PresentUse")).upper()
    if "VACANT" in blob and any(tok in blob for tok in ("COMMERCIAL", "INDUSTRIAL")):
        return LotSurface(kind="paved", source="assessor")
    if "VACANT" in blob and any(tok in blob for tok in ("RESIDENTIAL", "SINGLE", "MULTI")):
        return LotSurface(kind="vegetated", source="assessor")
    return LotSurface(kind="unknown", source="unknown")


def surface_sort_rank(kind: str | None, *, mostly_paved: bool = False) -> int:
    """Lower sorts first when preferring paved vacant."""
    if mostly_paved or (kind or "").strip().lower() == "paved":
        return 0
    k = (kind or "unknown").strip().lower()
    if k == "mixed":
        return 1
    if k == "unknown":
        return 2
    return 3  # vegetated last


def _is_vegetation(r: int, g: int, b: int) -> bool:
    return g > r + 12 and g > b + 8 and g > 55


def _is_pavement(r: int, g: int, b: int) -> bool:
    mx = max(r, g, b)
    mn = min(r, g, b)
    sat = 0.0 if mx == 0 else (mx - mn) / mx
    return sat < 0.22 and 45 <= mx <= 210


def _is_warm_dirt(r: int, g: int, b: int) -> bool:
    """Brown / tan soil — not a vehicle."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    sat = 0.0 if mx == 0 else (mx - mn) / mx
    if sat < 0.12 or mx < 40:
        return False
    return r >= g >= b and (r - b) < 90 and abs(r - g) < 45


def _is_vehicleish(r: int, g: int, b: int) -> bool:
    """Car-like pixels: white/silver, dark bodies, or chromatic (not green / brown dirt)."""
    if _is_vegetation(r, g, b) or _is_pavement(r, g, b) or _is_warm_dirt(r, g, b):
        return False
    mx = max(r, g, b)
    mn = min(r, g, b)
    sat = 0.0 if mx == 0 else (mx - mn) / mx
    # White / silver / light gray cars
    if mx >= 185 and sat <= 0.28:
        return True
    # Dark / black cars
    if 18 <= mx <= 58:
        return True
    # Chromatic body panels (red/blue/etc.)
    if sat >= 0.30:
        return True
    return False


def classify_lot_surface_pixels(
    image_bytes: bytes,
    *,
    geom: Any | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    width: int | None = None,
    height: int | None = None,
) -> LotSurface:
    """Classify paved vs vegetated and detect active parking from an aerial JPEG."""
    from PIL import Image, ImageDraw

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            mask = None
            if geom is not None and bbox is not None and width and height and width == w and height == h:
                from app.parcel_site_imagery import _lonlat_to_px, _rings_lonlat

                rings = _rings_lonlat(geom)
                if rings:
                    mask_img = Image.new("L", (w, h), 0)
                    draw = ImageDraw.Draw(mask_img)
                    for ring in rings:
                        pts = [_lonlat_to_px(lon, lat, bbox, w, h) for lon, lat in ring]
                        if len(pts) >= 3:
                            draw.polygon(pts, fill=255)
                    mask = mask_img
            px = rgb.load()
            paved = veg = veh = other = bright = 0
            step = 2 if w * h > 80_000 else 1
            for y in range(0, h, step):
                for x in range(0, w, step):
                    if mask is not None and mask.getpixel((x, y)) < 128:
                        continue
                    r, g, b = px[x, y]
                    if r + g + b < 40:
                        continue
                    mx = max(r, g, b)
                    if mx >= 165:
                        bright += 1
                    if _is_vegetation(r, g, b):
                        veg += 1
                    elif _is_pavement(r, g, b):
                        paved += 1
                    elif _is_vehicleish(r, g, b):
                        veh += 1
                    else:
                        other += 1
            total = paved + veg + veh + other
            if total < 30:
                return LotSurface(kind="unknown", source="aerial")
            pf = paved / total
            vf = veg / total
            veh_f = veh / total
            bright_f = bright / total
            if pf >= 0.38 and pf >= vf + 0.05:
                kind: SurfaceKind = "paved"
            elif vf >= 0.38 and vf >= pf + 0.05:
                kind = "vegetated"
            elif pf >= 0.28 and vf >= 0.28:
                kind = "mixed"
            elif pf >= vf:
                kind = "paved" if pf >= 0.25 else "mixed"
            else:
                kind = "vegetated" if vf >= 0.25 else "mixed"
            # Cars on asphalt → already an operating parking lot (poor prospect).
            # Esri often renders car roofs as near-white / light gray (bright_f).
            active = (pf >= _ACTIVE_PARKING_MIN_PAVED and veh_f >= _ACTIVE_PARKING_MIN_VEHICLE) or (
                pf >= _ACTIVE_PARKING_BRIGHT_PAVED and bright_f >= _ACTIVE_PARKING_MIN_BRIGHT
            )
            return LotSurface(
                kind=kind,
                paved_fraction=round(pf, 3),
                vegetated_fraction=round(vf, 3),
                vehicle_fraction=round(veh_f, 3),
                looks_like_active_parking=active,
                source="aerial",
            )
    except Exception as exc:
        logger.info("lot surface classify failed: %s", exc)
        return LotSurface(kind="unknown", source="unknown")


def resolve_lot_surface(
    raw_properties: dict[str, Any] | None,
    *,
    aerial: LotSurface | None = None,
) -> LotSurface:
    """Prefer aerial when confident; otherwise assessor prior."""
    if aerial is not None and aerial.kind != "unknown":
        return aerial
    hint = assessor_surface_hint(raw_properties)
    if aerial is not None and aerial.looks_like_active_parking:
        return LotSurface(
            kind=hint.kind if hint.kind != "unknown" else "paved",
            paved_fraction=aerial.paved_fraction,
            vegetated_fraction=aerial.vegetated_fraction,
            vehicle_fraction=aerial.vehicle_fraction,
            looks_like_active_parking=True,
            source="aerial",
        )
    return hint


def classify_parcel_aerial_surface(
    *,
    lat: float,
    lon: float,
    footprint: Any | None,
) -> LotSurface:
    """Fetch a tight Esri tile (no outline/letterbox) and classify the lot interior."""
    from app.parcel_site_imagery import _padded_bbox, _http_get_bytes, _ESRI_EXPORT
    import urllib.parse

    if footprint is None or getattr(footprint, "is_empty", True):
        return LotSurface(kind="unknown", source="unknown")
    minx, miny, maxx, maxy = footprint.bounds
    bbox = _padded_bbox(minx, miny, maxx, maxy, pad_frac=0.08, min_pad_m=6.0, min_span_m=36.0)
    # Keep geographic aspect; medium canvas so car roofs stay visible.
    mid_lat = (bbox[1] + bbox[3]) / 2.0
    import math

    m_per_deg_lat = 110_540.0
    m_per_deg_lon = 111_320.0 * max(0.2, math.cos(math.radians(mid_lat)))
    geo_w_m = max((bbox[2] - bbox[0]) * m_per_deg_lon, 1.0)
    geo_h_m = max((bbox[3] - bbox[1]) * m_per_deg_lat, 1.0)
    geo_aspect = geo_w_m / geo_h_m
    if geo_aspect >= 1.0:
        fetch_w = 400
        fetch_h = max(80, int(round(400 / geo_aspect)))
    else:
        fetch_h = 400
        fetch_w = max(80, int(round(400 * geo_aspect)))
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
    got = _http_get_bytes(f"{_ESRI_EXPORT}?{params}", timeout_s=12.0)
    if not got or len(got[0]) < 400:
        return LotSurface(kind="unknown", source="unknown")
    return classify_lot_surface_pixels(
        got[0],
        geom=footprint,
        bbox=bbox,
        width=fetch_w,
        height=fetch_h,
    )


def enrich_surfaces_from_aerial(
    items: list[tuple[UUID, float, float, Any]],
    *,
    max_workers: int = 10,
    deadline_s: float = 18.0,
) -> dict[UUID, LotSurface]:
    """Parallel aerial classify for ``(parcel_id, lat, lon, footprint)`` tuples."""
    import time

    out: dict[UUID, LotSurface] = {}
    if not items:
        return out
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {
            pool.submit(classify_parcel_aerial_surface, lat=lat, lon=lon, footprint=fp): pid
            for pid, lat, lon, fp in items
        }
        try:
            for fut in as_completed(futs, timeout=max(1.0, deadline_s)):
                if time.monotonic() - t0 > deadline_s:
                    break
                pid = futs[fut]
                try:
                    out[pid] = fut.result()
                except Exception as exc:
                    logger.info("aerial surface enrich failed for %s: %s", pid, exc)
        except TimeoutError:
            logger.info("aerial surface enrich hit deadline after %s results", len(out))
    return out
