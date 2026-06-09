"""Tests for county-specific situs/mailing normalization at ingest."""

from parking_ingestion.address_normalize import (
    has_usable_situs,
    looks_like_street,
    normalize_parcel_address_props,
)


def test_looks_like_street_rejects_zip_only():
    assert not looks_like_street("98032")
    assert looks_like_street("728 3RD AVE N")


def test_normalize_watech_king_fields():
    props = {
        "COUNTY_FIPS": "53033",
        "SITUS_ADDRESS": "728 3RD AVE N",
        "SITUS_CITY_NM": "KENT",
        "SITUS_ZIP_NR": "98032",
        "OWNER_NAME": "Example LLC",
    }
    assert normalize_parcel_address_props(props, county_fips="53033") is True
    assert props["PROPERTY_ADDRESS"] == "728 3RD AVE N"
    assert props["SITUS_CITY"] == "KENT"
    assert props["SITUS_ZIP"] == "98032"
    assert props["ADDRESS_SOURCE"] == "watech_king"


def test_normalize_skips_zip_only_situs():
    props = {
        "COUNTY_FIPS": "53033",
        "SITUS_ADDRESS": "98032",
        "SITUS_CITY_NM": "KENT",
        "SITUS_ZIP_NR": "98032",
    }
    assert normalize_parcel_address_props(props, county_fips="53033") is False
    assert "PROPERTY_ADDRESS" not in props


def test_normalize_skips_when_already_present():
    props = {
        "COUNTY_FIPS": "53033",
        "PROPERTY_ADDRESS": "100 Main St",
        "SITUS_ADDRESS": "100 Main St",
    }
    assert normalize_parcel_address_props(props, county_fips="53033") is False


def test_has_usable_situs_composed_line():
    props = {"SITUS_LINE1": "555 W SMITH ST", "SITUS_CITY": "KENT"}
    assert has_usable_situs(props)


def test_baltimore_county_skipped():
    props = {"COUNTY_FIPS": "24510", "SITUS_ADDRESS": "100 N Charles St"}
    assert normalize_parcel_address_props(props, county_fips="24510") is False
