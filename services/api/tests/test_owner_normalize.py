"""Unit tests for owner name normalization (multi-county rollup keys)."""

from __future__ import annotations

from parking_enrichment.owner_normalize import normalize_legal_name_core, scoped_owner_key


def test_normalize_strips_llc_and_punctuation() -> None:
    assert normalize_legal_name_core("Acme Holdings, LLC") == "ACME HOLDINGS"
    assert normalize_legal_name_core("  Foo BAR  INC.  ") == "FOO BAR"


def test_scoped_key_includes_state_prefix() -> None:
    k = scoped_owner_key("Acme Holdings LLC", county_fips="53033")
    assert k.startswith("53:")
    assert "ACME HOLDINGS" in k
