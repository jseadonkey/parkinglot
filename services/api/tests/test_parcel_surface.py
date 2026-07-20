"""Assessor + aerial surface hints for paved vacant preference."""

from __future__ import annotations

from app.parcel_surface import (
    assessor_surface_hint,
    classify_lot_surface_pixels,
    surface_sort_rank,
)


def test_assessor_commercial_vacant_is_paved() -> None:
    s = assessor_surface_hint({"LANDUSE_CD": "309", "VALUE_BLDG": "0", "VALUE_LAND": "1000000"})
    assert s.kind == "paved"
    assert s.source == "assessor"


def test_assessor_residential_vacant_is_vegetated() -> None:
    s = assessor_surface_hint({"LANDUSE_CD": "300"})
    assert s.kind == "vegetated"


def test_surface_sort_rank_paved_first() -> None:
    assert surface_sort_rank("paved") < surface_sort_rank("vegetated")
    assert surface_sort_rank("mixed") < surface_sort_rank("vegetated")


def test_classify_gray_image_as_paved() -> None:
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (64, 64), color=(110, 110, 112))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    s = classify_lot_surface_pixels(buf.getvalue())
    assert s.kind == "paved"
    assert (s.paved_fraction or 0) > 0.5


def test_classify_green_image_as_vegetated() -> None:
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (64, 64), color=(40, 140, 50))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    s = classify_lot_surface_pixels(buf.getvalue())
    assert s.kind == "vegetated"
