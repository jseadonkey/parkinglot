"""Resolve Article 32 principal-use parking symbols for API responses and filters."""

from __future__ import annotations

from parking_core.waza_provisional import provisional_symbol_from_raw
from parking_ingestion.zoning_rules import (
    all_zone_codes_for_tier,
    infer_zoning_jurisdiction,
    load_effective_zoning_rules,
    resolve_principal_use_symbol,
    zone_codes_for_tier,
    zoning_entitlement_tier,
)

ZoningTierFilter = str  # permitted | conditional | provisional | council | excluded

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
    """Resolve principal-use parking symbol from curated rules, else WAZA provisional.

    Stale ``zoning_principal_use_symbol`` caches (e.g. ``NOT_LISTED`` written before
    a jurisdiction had YAML entries) must not become UI \"Not allowed\" when the
    zone is still unmapped — that should stay ``unknown`` until counsel curates it.

    When no curated entry exists, WAZA ``COM`` / ``MXU`` / ``IND`` yields ``PV``
    (provisional prospect signal — not ``allows_surface_parking``).
    """
    raw = raw_properties or {}
    z_code = effective_zoning_code(zoning_code, raw)
    rules = load_effective_zoning_rules()
    juris = infer_zoning_jurisdiction(
        county_fips, raw.get("ZONING_JURISDICTION") or raw.get("zoning_jurisdiction")
    )
    if z_code:
        resolved = resolve_principal_use_symbol(z_code, juris, rules)
        if resolved is not None:
            return resolved
    return provisional_symbol_from_raw(raw)


def parcel_zoning_tier(
    *,
    county_fips: str,
    zoning_code: str | None,
    raw_properties: dict | None,
) -> str:
    """Operator-facing entitlement bucket; always derived from live symbol resolution."""
    raw = raw_properties or {}
    z_code = effective_zoning_code(zoning_code, raw)
    sym = parcel_zoning_symbol(
        county_fips=county_fips,
        zoning_code=z_code,
        raw_properties=raw,
    )
    return zoning_entitlement_tier(sym)


def baltimore_zone_codes_for_tier(tier: ZoningTierFilter) -> set[str]:
    rules = load_effective_zoning_rules()
    return zone_codes_for_tier("baltimore_city", tier, rules)


def curated_zone_codes_for_tier(tier: ZoningTierFilter) -> set[str]:
    """Zone codes matching ``tier`` across all curated jurisdiction YAML files."""
    rules = load_effective_zoning_rules()
    return all_zone_codes_for_tier(tier, rules)
