"""Address source chain rotation (catalog-driven, no DB)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "address-health-agent"))

from lib.chains import advance_source, source_chain_for_county  # noqa: E402
from lib.connectors import ARCGIS_ADDRESS_SOURCES  # noqa: E402


def test_king_chain_order():
    chain = source_chain_for_county("53033")
    assert chain[0] == "watech_statewide_parcels"
    assert "king_assessor_roll" in chain
    assert chain[-1] == "nominatim_centroid_fallback"


def test_advance_source_rotates():
    nxt, rotated = advance_source("53033", "watech_statewide_parcels")
    assert rotated is True
    assert nxt == "king_assessor_roll"


def test_baltimore_chain():
    chain = source_chain_for_county("24510")
    assert chain == ["baltimore_realproperty", "baltimore_address_points"]


def test_active_puget_counties_have_post_centroid_sources():
    """Persisted deployed state can already be on the old centroid fallback."""
    expected = {
        "53053": "pierce_tax_parcels",
        "53061": "snohomish_current_parcels",
        "53035": "kitsap_county_parcels_retry",
        "53067": "thurston_county_parcels_retry",
    }
    for county_fips, next_source in expected.items():
        nxt, rotated = advance_source(county_fips, "nominatim_centroid_fallback")
        assert rotated is True
        assert nxt == next_source
        assert next_source in ARCGIS_ADDRESS_SOURCES


def test_public_arcgis_address_sources_have_join_fields():
    for config in ARCGIS_ADDRESS_SOURCES.values():
        assert config["url"]
        assert config["join_fields"]
        assert config["address_fields"]
