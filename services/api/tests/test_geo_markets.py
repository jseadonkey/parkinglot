from __future__ import annotations

from app.geo_markets import load_geo_markets, primary_market_summary, priority_county_fips


def test_primary_market_is_baltimore() -> None:
    summary = primary_market_summary("config/geo_markets.yaml")
    assert summary["name"] == "Baltimore, Maryland"
    assert summary["state_fips"] == "24"


def test_priority_counties_baltimore_first() -> None:
    assert load_geo_markets("config/geo_markets.yaml")
    fips = priority_county_fips("config/geo_markets.yaml")
    assert fips[:2] == ["24510", "24005"]
