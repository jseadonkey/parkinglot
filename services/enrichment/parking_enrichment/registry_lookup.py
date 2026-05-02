"""Optional automated registry lookups (state SOS). Prefer stable official APIs where they exist."""

from __future__ import annotations

from urllib.parse import quote_plus

from parking_core.models import OwnerKind, RegistryLookupSummary


def wa_ccfs_search_url_for_manual_review(entity_name: str) -> str:
    """Landing URL for WA Corporations & Charities Filing System (human completes search)."""
    q = quote_plus(entity_name.strip())
    return f"https://ccfs.sos.wa.gov/#/BusinessSearch?SearchCriteria={q}"


def lookup_secretary_of_state_stub(
    *,
    county_fips: str,
    owner_kind: OwnerKind,
    query_name: str,
) -> RegistryLookupSummary | None:
    """Return a registry summary row for persistence on the outreach brief.

    Automated JSON endpoints for WA SOS have moved behind SPA redirects; we record a
    human-actionable CCFS URL plus outcome metadata. Expand with HTTP calls when a
    supported API contract exists for your deployment.
    """
    if owner_kind != OwnerKind.entity:
        return RegistryLookupSummary(
            state=(county_fips or "")[:2] or "??",
            provider="secretary_of_state_stub",
            query_used=query_name,
            outcome="skipped_not_entity",
            notes="SOS business lookup applies to entities; use grantor/grantee and assessor for individuals.",
        )

    cf = (county_fips or "").strip()
    if len(cf) != 5:
        return RegistryLookupSummary(
            state="??",
            provider="secretary_of_state_stub",
            query_used=query_name,
            outcome="error",
            error_detail="invalid county_fips",
        )

    if not cf.startswith("53"):
        return RegistryLookupSummary(
            state=cf[:2],
            provider="secretary_of_state_stub",
            query_used=query_name,
            outcome="skipped_not_wa",
            notes="Non-Washington county — plug in that state's SOS / registry provider.",
        )

    url = wa_ccfs_search_url_for_manual_review(query_name)
    return RegistryLookupSummary(
        state="53",
        provider="wa_sos_ccfs",
        query_used=query_name,
        outcome="manual_url_only",
        search_results_url=url,
        notes=(
            "Open CCFS from search_results_url; confirm UBI, registered agent, and principal "
            "address before outreach."
        ),
    )
