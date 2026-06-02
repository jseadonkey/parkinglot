from __future__ import annotations

from pathlib import Path

from app.geo_markets import load_geo_markets, primary_market_summary, priority_county_fips

_REPO = Path(__file__).resolve().parents[3]
_GEO_MARKETS = str(_REPO / "config/geo_markets.yaml")


def test_primary_market_is_baltimore() -> None:
    summary = primary_market_summary(_GEO_MARKETS)
    assert summary["name"] == "Baltimore, Maryland"
    assert summary["state_fips"] == "24"


def test_priority_counties_baltimore_first() -> None:
    raw = load_geo_markets(_GEO_MARKETS)
    assert raw.get("primary_market")
    fips = priority_county_fips(_GEO_MARKETS)
    assert fips == ["24510"]
