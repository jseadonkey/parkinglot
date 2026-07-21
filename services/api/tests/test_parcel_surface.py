"""Assessor + aerial surface hints for paved vacant preference."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.parcel_surface import (
    assessor_surface_hint,
    classify_lot_surface_pixels,
    surface_sort_rank,
)


def test_assessor_commercial_vacant_is_paved() -> None:
    s = assessor_surface_hint({"LANDUSE_CD": "309", "VALUE_BLDG": "0", "VALUE_LAND": "1000000"})
    assert s.kind == "paved"
    assert s.source == "assessor"
    assert s.looks_like_active_parking is False


def test_assessor_residential_vacant_is_vegetated() -> None:
    s = assessor_surface_hint({"LANDUSE_CD": "300"})
    assert s.kind == "vegetated"


def test_surface_sort_rank_paved_first() -> None:
    assert surface_sort_rank("paved") < surface_sort_rank("vegetated")
    assert surface_sort_rank("mixed") < surface_sort_rank("vegetated")


def test_classify_gray_image_as_paved_empty() -> None:
    img = Image.new("RGB", (64, 64), color=(110, 110, 112))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    s = classify_lot_surface_pixels(buf.getvalue())
    assert s.kind == "paved"
    assert (s.paved_fraction or 0) > 0.5
    assert s.looks_like_active_parking is False


def test_classify_green_image_as_vegetated() -> None:
    img = Image.new("RGB", (64, 64), color=(40, 140, 50))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    s = classify_lot_surface_pixels(buf.getvalue())
    assert s.kind == "vegetated"


def test_classify_bright_roofs_on_asphalt_as_active_parking() -> None:
    """Mostly asphalt with scattered near-white car roofs → operating lot.

    Keep roof coverage under the building threshold (~0.22) so a busy lot is
    not mistaken for a single large rooftop.
    """
    img = Image.new("RGB", (100, 100), color=(105, 105, 108))
    px = img.load()
    for y in range(100):
        for x in range(100):
            if (x // 5 + y // 5) % 8 == 0:
                px[x, y] = (200, 200, 205)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    s = classify_lot_surface_pixels(buf.getvalue())
    assert s.looks_like_active_parking is True
    assert s.looks_like_building is False
    assert (s.paved_fraction or 0) >= 0.55


def test_classify_large_bright_roof_as_building() -> None:
    """A large white/metal rooftop covering most of the parcel → already built."""
    img = Image.new("RGB", (100, 100), color=(105, 105, 108))
    px = img.load()
    for y in range(15, 85):
        for x in range(15, 85):
            px[x, y] = (220, 218, 210)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    s = classify_lot_surface_pixels(buf.getvalue())
    assert s.looks_like_building is True
    assert s.looks_like_active_parking is False
    assert (s.roof_fraction or 0) >= 0.22
