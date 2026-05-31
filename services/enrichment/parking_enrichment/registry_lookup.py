"""Washington Secretary of State (CCFS) registry lookups for entity owners."""

from __future__ import annotations

import time
from typing import Any

from parking_core.models import OwnerKind, RegistryLookupSummary, RegistryPrincipal
from parking_enrichment.wa_sos_ccfs_client import (
    lookup_wa_entity_via_ccfs,
    wa_ccfs_search_url_for_manual_review,
)

_LAST_LOOKUP_MONO: float | None = None


def _redis_rate_limit(redis_url: str | None, min_delay_s: float) -> None:
    """Best-effort cross-process spacing via Redis; falls back to in-process sleep."""
    global _LAST_LOOKUP_MONO
    if redis_url:
        try:
            import redis

            client = redis.from_url(redis_url, decode_responses=True)
            key = "wa_sos:last_lookup_mono"
            while True:
                now = time.monotonic()
                prev_raw = client.get(key)
                prev = float(prev_raw) if prev_raw else 0.0
                wait = min_delay_s - (now - prev)
                if wait <= 0:
                    client.set(key, str(now), ex=max(int(min_delay_s * 4), 300))
                    _LAST_LOOKUP_MONO = now
                    return
                time.sleep(min(wait, 5.0))
        except Exception:
            pass

    now = time.monotonic()
    if _LAST_LOOKUP_MONO is not None:
        wait = min_delay_s - (now - _LAST_LOOKUP_MONO)
        if wait > 0:
            time.sleep(wait)
    _LAST_LOOKUP_MONO = time.monotonic()


def lookup_secretary_of_state(
    *,
    enabled: bool,
    county_fips: str,
    owner_kind: OwnerKind,
    query_name: str,
    min_delay_s: float = 60.0,
    redis_url: str | None = None,
) -> RegistryLookupSummary | None:
    """Automated WA CCFS lookup when enabled; otherwise a manual CCFS URL stub."""
    if owner_kind != OwnerKind.entity:
        return RegistryLookupSummary(
            state=(county_fips or "")[:2] or "??",
            provider="secretary_of_state",
            query_used=query_name,
            outcome="skipped_not_entity",
            notes="SOS business lookup applies to entities; use grantor/grantee and assessor for individuals.",
        )

    cf = (county_fips or "").strip()
    if len(cf) != 5:
        return RegistryLookupSummary(
            state="??",
            provider="secretary_of_state",
            query_used=query_name,
            outcome="error",
            error_detail="invalid county_fips",
        )

    if not cf.startswith("53"):
        return RegistryLookupSummary(
            state=cf[:2],
            provider="secretary_of_state",
            query_used=query_name,
            outcome="skipped_not_wa",
            notes="Non-Washington county — plug in that state's SOS / registry provider.",
        )

    manual_url = wa_ccfs_search_url_for_manual_review(query_name)
    if not enabled:
        return RegistryLookupSummary(
            state="53",
            provider="wa_sos_ccfs",
            query_used=query_name,
            outcome="manual_url_only",
            search_results_url=manual_url,
            notes="Automated WA SOS disabled — open CCFS manually or set WA_SOS_LOOKUP_ENABLED=true.",
        )

    _redis_rate_limit(redis_url, max(min_delay_s, 15.0))
    result = lookup_wa_entity_via_ccfs(query_name, min_delay_s=0)

    principals = [
        RegistryPrincipal(name=p.get("name"), role=p.get("role"), address=p.get("address"))
        for p in (result.principals or [])
        if isinstance(p, dict)
    ]

    if result.outcome == "hit":
        return RegistryLookupSummary(
            state="53",
            provider="wa_sos_ccfs",
            query_used=query_name,
            outcome="hit",
            raw_result_count=result.raw_result_count,
            top_match_name=result.top_match_name,
            top_match_ubi=result.top_match_ubi,
            search_results_url=manual_url,
            detail_url=result.detail_url,
            registered_agent_line=result.registered_agent_line,
            registered_agent_address=result.registered_agent_address,
            principal_address_line=result.principal_address_line,
            principals=principals,
            notes=result.notes,
        )

    if result.outcome == "no_results":
        return RegistryLookupSummary(
            state="53",
            provider="wa_sos_ccfs",
            query_used=query_name,
            outcome="no_results",
            raw_result_count=result.raw_result_count,
            search_results_url=manual_url,
            detail_url=result.detail_url,
            error_detail=result.error_detail,
            notes=result.notes,
        )

    return RegistryLookupSummary(
        state="53",
        provider="wa_sos_ccfs",
        query_used=query_name,
        outcome="error",
        search_results_url=manual_url,
        detail_url=result.detail_url,
        error_detail=result.error_detail,
        notes=result.notes or "Automated CCFS lookup failed — use manual CCFS link.",
    )


def lookup_secretary_of_state_stub(
    *,
    county_fips: str,
    owner_kind: OwnerKind,
    query_name: str,
) -> RegistryLookupSummary | None:
    """Backward-compatible stub — manual CCFS URL only."""
    return lookup_secretary_of_state(
        enabled=False,
        county_fips=county_fips,
        owner_kind=owner_kind,
        query_name=query_name,
    )


def registry_principals_as_persons(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten registry principals + registered agent for owner_record_view."""
    persons: list[dict[str, Any]] = []
    provider = registry.get("provider") or "registry"

    agent = registry.get("registered_agent_line")
    agent_addr = registry.get("registered_agent_address") or registry.get("principal_address_line")
    if agent:
        persons.append(
            {
                "name": agent,
                "role": "registered_agent",
                "address": agent_addr,
                "phone": None,
                "email": None,
                "source": provider,
            }
        )

    for item in registry.get("principals") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        persons.append(
            {
                "name": name,
                "role": item.get("role") or "principal",
                "address": item.get("address"),
                "phone": None,
                "email": None,
                "source": provider,
            }
        )

    if not persons:
        top = registry.get("top_match_name")
        principal_addr = registry.get("principal_address_line")
        if top and principal_addr:
            persons.append(
                {
                    "name": top,
                    "role": "registry_match",
                    "address": principal_addr,
                    "phone": None,
                    "email": None,
                    "source": provider,
                }
            )
    return persons
