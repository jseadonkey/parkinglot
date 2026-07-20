"""Unit tests for parcel site imagery helpers."""

from unittest.mock import MagicMock, patch

from app.parcel_site_imagery import (
    fetch_satellite_image,
    fetch_site_image,
    fetch_street_view_image,
    satellite_map_url,
    street_view_url,
)


def test_street_view_and_satellite_urls() -> None:
    assert "map_action=pano" in street_view_url(47.38, -122.23)
    assert "47.380000" in satellite_map_url(47.38, -122.23)


def test_fetch_satellite_image_ok() -> None:
    fake = (b"JPEGDATA" + b"x" * 600, "image/jpeg")
    with patch("app.parcel_site_imagery._http_get_bytes", return_value=fake):
        img = fetch_satellite_image(47.38, -122.23, width=320, height=240)
    assert img is not None
    assert img.source == "satellite"
    assert img.content_type == "image/jpeg"


def test_fetch_street_view_requires_key() -> None:
    settings = MagicMock(google_maps_api_key="")
    with patch("app.parcel_site_imagery.get_settings", return_value=settings):
        assert fetch_street_view_image(47.38, -122.23) is None


def test_fetch_site_image_auto_falls_back_to_satellite() -> None:
    fake = (b"JPEGDATA" + b"x" * 600, "image/jpeg")
    settings = MagicMock(google_maps_api_key="")
    with (
        patch("app.parcel_site_imagery.get_settings", return_value=settings),
        patch("app.parcel_site_imagery._http_get_bytes", return_value=fake),
    ):
        img = fetch_site_image(47.38, -122.23, source="auto")
    assert img is not None
    assert img.source == "satellite"
