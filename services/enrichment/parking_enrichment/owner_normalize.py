"""Normalize recorded owner names into stable keys for multi-parcel / multi-county rollup.

Keys are scoped by US state (first two digits of county FIPS) to reduce accidental merges
across states. Tune normalization before relying on cross-county portfolio totals.
"""

from __future__ import annotations

import re
import unicodedata


def _collapse_ws(s: str) -> str:
    return " ".join(s.split())


def normalize_legal_name_core(name: str) -> str:
    """Uppercase, strip punctuation noise, drop common corporate suffix tokens."""
    raw = unicodedata.normalize("NFKC", name).strip()
    if not raw:
        return ""

    upper = raw.upper()
    # Remove punctuation except & (common in entity names).
    upper = re.sub(r"[^\w\s&'-]", " ", upper, flags=re.UNICODE)
    upper = _collapse_ws(upper)

    suffix_tokens = (
        "LLC",
        "L L C",
        "L.L.C",
        "INC",
        "CORP",
        "CORPORATION",
        "CO",
        "LP",
        "LLP",
        "PLLC",
        "PC",
        "TRUST",
        "TRUSTEE",
        "INCORPORATED",
        "LIMITED",
        "LTD",
        "PARTNERSHIP",
        "COMPANY",
    )
    parts = upper.split()
    while parts and parts[-1] in suffix_tokens:
        parts.pop()
    while parts and parts[0] in suffix_tokens:
        parts.pop(0)

    return _collapse_ws(" ".join(parts))


def scoped_owner_key(display_name: str, *, county_fips: str, max_len: int = 256) -> str:
    """Return ``SS:NAME`` where SS is the state FIPS prefix (county FIPS first two digits)."""
    cf = (county_fips or "").strip()
    state = cf[:2] if len(cf) >= 2 else ""
    core = normalize_legal_name_core(display_name)
    if not core:
        return f"{state}:UNKNOWN"[:max_len]
    key = f"{state}:{core}"
    return key[:max_len]
