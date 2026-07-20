"""Lot surface hints: paved vs vegetated (assessor + aerial).

Operators prefer downtown **paved vacant** pads (empty asphalt / concrete)
over grassy undeveloped lots. Assessor Present Use is a fast prior; aerial
pixels refine the label when imagery is available.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

SurfaceKind = Literal["paved", "vegetated", "mixed", "unknown"]

# King vacant commercial / industrial — usually paved or hard-surface pads.
_PAVED_LIKELY_LANDUSE = frozenset({"309", "316"})
# King vacant residential — usually grass / dirt.
_VEGETATED_LIKELY_LANDUSE = frozenset({"300", "301", "299"})


@dataclass(frozen=True)
class LotSurface:
    kind: SurfaceKind
    paved_fraction: float | None = None
    vegetated_fraction: float | None = None
    source: Literal["assessor", "aerial", "unknown"] = "unknown"


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
    if "VACANT" in blob and any(tok in blob for tok in ("COMMERCIAL", "INDUSTRIAL", "PARKING")):
        return LotSurface(kind="paved", source="assessor")
    if "VACANT" in blob and any(tok in blob for tok in ("RESIDENTIAL", "SINGLE", "MULTI")):
        return LotSurface(kind="vegetated", source="assessor")
    return LotSurface(kind="unknown", source="unknown")


def surface_sort_rank(kind: str | None) -> int:
    """Lower sorts first when preferring paved vacant."""
    k = (kind or "unknown").strip().lower()
    if k == "paved":
        return 0
    if k == "mixed":
        return 1
    if k == "unknown":
        return 2
    return 3  # vegetated last


def classify_lot_surface_pixels(
    image_bytes: bytes,
    *,
    geom: Any | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    width: int | None = None,
    height: int | None = None,
) -> LotSurface:
    """Classify paved vs vegetated from an aerial JPEG (optionally masked to the lot)."""
    from PIL import Image, ImageDraw

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            mask = None
            if geom is not None and bbox is not None and width and height:
                from app.parcel_site_imagery import _lonlat_to_px, _rings_lonlat

                rings = _rings_lonlat(geom)
                if rings:
                    mask_img = Image.new("L", (w, h), 0)
                    draw = ImageDraw.Draw(mask_img)
                    # Image may be letterboxed; map using the fetch canvas size when given.
                    use_w = width if width == w else w
                    use_h = height if height == h else h
                    # If letterboxed, scale polygon into the centered tile — skip mask and use full image.
                    if use_w == w and use_h == h:
                        for ring in rings:
                            pts = [_lonlat_to_px(lon, lat, bbox, w, h) for lon, lat in ring]
                            if len(pts) >= 3:
                                draw.polygon(pts, fill=255)
                        mask = mask_img
            px = rgb.load()
            paved = veg = other = 0
            step = 2 if w * h > 80_000 else 1
            for y in range(0, h, step):
                for x in range(0, w, step):
                    if mask is not None and mask.getpixel((x, y)) < 128:
                        continue
                    # Skip near-black letterbox bars.
                    r, g, b = px[x, y]
                    if r + g + b < 40:
                        continue
                    mx = max(r, g, b)
                    mn = min(r, g, b)
                    sat = 0.0 if mx == 0 else (mx - mn) / mx
                    # Vegetation: green-dominant, moderate brightness.
                    if g > r + 12 and g > b + 8 and g > 55:
                        veg += 1
                    # Pavement / asphalt / concrete: low saturation gray.
                    elif sat < 0.22 and 45 <= mx <= 210:
                        paved += 1
                    else:
                        other += 1
            total = paved + veg + other
            if total < 30:
                return LotSurface(kind="unknown", source="aerial")
            pf = paved / total
            vf = veg / total
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
            return LotSurface(
                kind=kind,
                paved_fraction=round(pf, 3),
                vegetated_fraction=round(vf, 3),
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
    return assessor_surface_hint(raw_properties)
