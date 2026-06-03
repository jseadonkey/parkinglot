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
    if not zoning_code or not str(zoning_code).strip():
        return None
    rules = load_effective_zoning_rules()
    juris = infer_zoning_jurisdiction(county_fips, raw.get("ZONING_JURISDICTION") or raw.get("zoning_jurisdiction"))
    return resolve_principal_use_symbol(str(zoning_code), juris, rules)


def parcel_zoning_tier(
    *,
    county_fips: str,
    zoning_code: str | None,
    raw_properties: dict | None,
) -> str:
    raw = raw_properties or {}
    cached = raw.get("zoning_entitlement_tier")
    if cached is not None and str(cached).strip():
        return str(cached).strip().lower()
    sym = parcel_zoning_symbol(
        county_fips=county_fips,
        zoning_code=zoning_code,
        raw_properties=raw,
    )
    return zoning_entitlement_tier(sym)


def baltimore_zone_codes_for_tier(tier: ZoningTierFilter) -> set[str]:
    rules = load_effective_zoning_rules()
    return zone_codes_for_tier("baltimore_city", tier, rules)
