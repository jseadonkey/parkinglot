"""Address source chain rotation (catalog-driven, no DB)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "address-health-agent"))

from lib.chains import advance_source, source_chain_for_county  # noqa: E402


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
