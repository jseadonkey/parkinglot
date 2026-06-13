"""Resolve Article 32 principal-use parking symbols for API responses and filters."""

from __future__ import annotations

from parking_ingestion.zoning_rules import (
    infer_zoning_jurisdiction,
    load_effective_zoning_rules,
    resolve_principal_use_symbol,
    zone_codes_for_tier,
    zoning_entitlement_tier,
)

ZoningTierFilter = str  # permitted | conditional | council | excluded

ZONING_CODE_KEYS: tuple[str, ...] = (
    "ZONING",
    "Zoning",
    "zoning_code",
    "ZONE",
    "zone",
    "ZONECODE",
    "zonecode",
    "ZONING_CLASS",
    "ZONING_CODE",
    "DISTRICT",
    "ZONING_DESC",
    "ZN_CODE",
    "ZONECLASS",
    "GIS_LU_CODE",
)


def effective_zoning_code(zoning_code: str | None, raw_properties: dict | None) -> str | None:
    """Return the normalized zoning source value, including vendor-specific raw fields."""
    if zoning_code is not None and str(zoning_code).strip():
        return str(zoning_code).strip()
    raw = raw_properties or {}
    for key in ZONING_CODE_KEYS:
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def parcel_zoning_symbol(
    *,
    county_fips: str,
    zoning_code: str | None,
    raw_properties: dict | None,
) -> str | None:
    raw = raw_properties or {}
    cached = raw.get("zoning_principal_use_symbol")
    if cached is not None and str(cached).strip():
        return str(cached).strip().upper()
    z_code = effective_zoning_code(zoning_code, raw)
    if not z_code:
        return None
    rules = load_effective_zoning_rules()
    juris = infer_zoning_jurisdiction(county_fips, raw.get("ZONING_JURISDICTION") or raw.get("zoning_jurisdiction"))
    return resolve_principal_use_symbol(z_code, juris, rules)


def parcel_zoning_tier(
    *,
    county_fips: str,
    zoning_code: str | None,
    raw_properties: dict | None,
) -> str:
    raw = raw_properties or {}
    z_code = effective_zoning_code(zoning_code, raw)
    cached = raw.get("zoning_entitlement_tier")
    if cached is not None and str(cached).strip():
        cached_s = str(cached).strip().lower()
        if cached_s != "unknown" or not z_code:
            return cached_s
    sym = parcel_zoning_symbol(
        county_fips=county_fips,
        zoning_code=z_code,
        raw_properties=raw,
    )
    return zoning_entitlement_tier(sym)


def baltimore_zone_codes_for_tier(tier: ZoningTierFilter) -> set[str]:
    rules = load_effective_zoning_rules()
    return zone_codes_for_tier("baltimore_city", tier, rules)
