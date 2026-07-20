"""Unit tests for parcel site imagery helpers."""

from io import BytesIO
from unittest.mock import MagicMock, patch

from PIL import Image
from shapely.geometry import box

from app.parcel_site_imagery import (
    fetch_satellite_image,
    fetch_site_image,
    fetch_street_view_image,
    footprint_image_bbox,
    overlay_lot_outline,
    satellite_map_url,
    street_view_url,
)


def test_street_view_and_satellite_urls() -> None:
    assert "map_action=pano" in street_view_url(47.38, -122.23)
    assert "47.380000" in satellite_map_url(47.38, -122.23)


def _tiny_jpeg(width: int = 320, height: int = 240) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=(40, 80, 40)).save(buf, format="JPEG")
    return buf.getvalue()


def test_fetch_satellite_image_ok() -> None:
    fake = (_tiny_jpeg(), "image/jpeg")
    with patch("app.parcel_site_imagery._http_get_bytes", return_value=fake):
        img = fetch_satellite_image(47.38, -122.23, width=320, height=240)
    assert img is not None
    assert img.source == "satellite"
    assert img.content_type == "image/jpeg"


def test_fetch_satellite_uses_footprint_bbox_and_outline() -> None:
    geom = box(-122.236, 47.383, -122.2355, 47.384)
    bbox = footprint_image_bbox(geom, width=320, height=240)
    assert bbox is not None
    # Padded fitted helper still expands for callers that need aspect-matched frames.
    assert bbox[0] < -122.236
    assert bbox[2] > -122.2355

    fake = (_tiny_jpeg(80, 240), "image/jpeg")  # skinny tile before letterbox
    with patch("app.parcel_site_imagery._http_get_bytes", return_value=fake) as http:
        img = fetch_satellite_image(47.38, -122.23, width=320, height=240, footprint=geom)
    assert img is not None
    assert img.source == "satellite"
    called_url = http.call_args[0][0]
    assert "bbox=" in called_url
    # Final canvas is the requested UI size (letterboxed if needed).
    with Image.open(BytesIO(img.body)) as out:
        assert out.size == (320, 240)


def test_overlay_lot_outline_draws_without_error() -> None:
    geom = box(-122.236, 47.383, -122.2355, 47.384)
    bbox = footprint_image_bbox(geom, width=160, height=120)
    assert bbox is not None
    out = overlay_lot_outline(_tiny_jpeg(160, 120), geom, bbox, width=160, height=120)
    assert out[:2] == b"\xff\xd8"  # JPEG SOI


def test_fetch_street_view_requires_key() -> None:
    settings = MagicMock(google_maps_api_key="")
    with patch("app.parcel_site_imagery.get_settings", return_value=settings):
        assert fetch_street_view_image(47.38, -122.23) is None


def test_fetch_site_image_prefers_satellite_when_footprint() -> None:
    geom = box(-122.236, 47.383, -122.2355, 47.384)
    fake = (_tiny_jpeg(), "image/jpeg")
    settings = MagicMock(google_maps_api_key="fake-key")
    with (
        patch("app.parcel_site_imagery.get_settings", return_value=settings),
        patch("app.parcel_site_imagery._http_get_bytes", return_value=fake),
        patch("app.parcel_site_imagery.fetch_street_view_image") as street,
    ):
        img = fetch_site_image(47.38, -122.23, source="auto", footprint=geom)
    assert img is not None
    assert img.source == "satellite"
    street.assert_not_called()
