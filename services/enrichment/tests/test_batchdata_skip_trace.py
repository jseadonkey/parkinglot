from parking_enrichment.batchdata_skip_trace_client import (
    property_address_for_skip_trace,
    reverse_geocode_street,
    should_skip_skip_trace,
)
from parking_enrichment.owner_outreach_agent import _situs_from_props


def test_property_address_watech_city_zip_fields():
    addr = property_address_for_skip_trace(
        {
            "SITUS_ADDRESS": "728 3RD AVE N",
            "SITUS_CITY_NM": "KENT",
            "SITUS_ZIP_NR": "98032",
        }
    )
    assert addr == {
        "street": "728 3RD AVE N",
        "city": "KENT",
        "state": "WA",
        "zip": "98032",
    }


def test_property_address_rejects_zip_only_situs():
    assert property_address_for_skip_trace(
        {
            "SITUS_ADDRESS": "98032",
            "SITUS_CITY_NM": "KENT",
            "SITUS_ZIP_NR": "98032",
        }
    ) is None


def test_property_address_composes_street_with_wa_city_zip():
    addr = property_address_for_skip_trace(
        {
            "SITUS_ADDRESS": None,
            "FULLADDR": "1004 W JAMES ST",
            "SITUS_CITY_NM": "KENT",
            "SITUS_ZIP_NR": "98032",
        }
    )
    assert addr is not None
    assert addr["street"] == "1004 W JAMES ST"
    assert addr["city"] == "KENT"
    assert addr["zip"] == "98032"


def test_situs_from_props_ignores_zip_only_watech_values():
    assert _situs_from_props(
        {
            "SITUS_ADDRESS": "98032",
            "SITUS_CITY_NM": "KENT",
            "SITUS_ZIP_NR": "98032",
        }
    ) == []


def test_situs_from_props_joins_wa_parts():
    out = _situs_from_props(
        {
            "SITUS_ADDRESS": "555 W SMITH ST",
            "SITUS_CITY_NM": "KENT",
            "SITUS_ZIP_NR": "98032",
        }
    )
    assert out == ["555 W SMITH ST, KENT, WA, 98032"]


def test_property_address_geocode_fills_from_nominatim_when_zip_only(monkeypatch):
    monkeypatch.setattr(
        "parking_enrichment.batchdata_skip_trace_client.reverse_geocode_street",
        lambda *_a, **_k: {"street": "100 Main St", "city": "Kent", "state": "WA", "zip": "98032"},
    )
    props = {"SITUS_ZIP_NR": "98032"}  # ZIP only — common WaTech shape
    addr = property_address_for_skip_trace(props, centroid_lat_lon=(47.38, -122.23))
    assert addr == {"street": "100 Main St", "city": "Kent", "state": "WA", "zip": "98032"}
    # Still refuse totally blank props (no assessor + geocode returned incomplete).
    monkeypatch.setattr(
        "parking_enrichment.batchdata_skip_trace_client.reverse_geocode_street",
        lambda *_a, **_k: None,
    )
    assert property_address_for_skip_trace({}, centroid_lat_lon=(47.38, -122.23)) is None


def test_property_address_geocode_prefers_assessor_city_zip(monkeypatch):
    monkeypatch.setattr(
        "parking_enrichment.batchdata_skip_trace_client.reverse_geocode_street",
        lambda *_a, **_k: {"street": "100 Main St", "city": "OSM", "state": "WA", "zip": "98032"},
    )
    props = {"SITUS_CITY_NM": "KENT", "SITUS_ZIP_NR": "98032"}
    addr = property_address_for_skip_trace(props, centroid_lat_lon=(47.38, -122.23))
    assert addr == {"street": "100 Main St", "city": "KENT", "state": "WA", "zip": "98032"}

def test_should_skip_skip_trace_when_roll_has_phone_and_email():
    assert should_skip_skip_trace({"OWNER_PHONE": "2065550100", "OWNER_EMAIL": "a@b.com"}) is not None


def test_reverse_geocode_street_kent_area():
    # Kent City Hall — stable OSM anchor near top-ranked Kent parcels.
    addr = reverse_geocode_street(47.3815, -122.2348)
    assert addr is not None
    assert _looks_like_street(addr["street"])
    assert addr["zip"]


def _looks_like_street(value: str) -> bool:
    from parking_enrichment.batchdata_skip_trace_client import _looks_like_street as check

    return check(value)
