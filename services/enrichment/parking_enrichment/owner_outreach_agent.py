from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from parking_core.models import (
    OutreachChannel,
    OutreachStep,
    OwnerCandidate,
    OwnerKind,
    OwnerOutreachBrief,
    RegistryLookupSummary,
    VendorLookupSummary,
)

_WA_STATE_FIPS_PREFIX = "53"


def _strip_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _join_address_parts(*parts: str | None) -> str | None:
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    if not cleaned:
        return None
    return ", ".join(cleaned)


def _mailing_from_props(props: dict[str, Any]) -> str | None:
    single_keys = (
        "MAIL_ADDR",
        "mail_addr",
        "MAILING_ADDRESS",
        "mailing_address",
        "OWNER_MAILING",
        "owner_mailing",
        "FULL_MAILING",
        "full_mailing",
        "MAIL_FULL",
        "mail_full",
    )
    for k in single_keys:
        line = _strip_str(props.get(k))
        if line:
            return line
    line1 = _strip_str(props.get("MAIL_LINE1") or props.get("mail_line1") or props.get("MAIL_STREET"))
    line2 = _strip_str(props.get("MAIL_LINE2") or props.get("mail_line2"))
    city = _strip_str(props.get("MAIL_CITY") or props.get("mail_city"))
    state = _strip_str(props.get("MAIL_STATE") or props.get("mail_state"))
    z = _strip_str(props.get("MAIL_ZIP") or props.get("mail_zip") or props.get("ZIP"))
    return _join_address_parts(line1, line2, city, _join_address_parts(state, z) if state or z else None)


def _situs_from_props(props: dict[str, Any]) -> str | None:
    single_keys = (
        "SITUS_ADDR",
        "situs_addr",
        "SITUS_ADDRESS",
        "PROPERTY_ADDRESS",
        "property_address",
        "PROP_ADDR",
        "prop_addr",
        "SITE_ADDR",
        "site_addr",
        "ADDR_FULL",
        "addr_full",
    )
    for k in single_keys:
        line = _strip_str(props.get(k))
        if line:
            return line
    line1 = _strip_str(props.get("SITUS_LINE1") or props.get("situs_line1") or props.get("LOC_STREET"))
    city = _strip_str(props.get("SITUS_CITY") or props.get("situs_city") or props.get("LOC_CITY"))
    state = _strip_str(props.get("SITUS_STATE") or props.get("situs_state"))
    z = _strip_str(props.get("SITUS_ZIP") or props.get("situs_zip"))
    return _join_address_parts(line1, city, _join_address_parts(state, z) if state or z else None)


def _phone_from_props(props: dict[str, Any]) -> str | None:
    for k in (
        "OWNER_PHONE",
        "owner_phone",
        "PHONE",
        "phone",
        "DAY_PHONE",
        "day_phone",
    ):
        raw = _strip_str(props.get(k))
        if raw:
            digits = re.sub(r"\D", "", raw)
            if len(digits) >= 10:
                return raw
            if raw:
                return raw
    return None


def _email_from_props(props: dict[str, Any]) -> str | None:
    for k in ("OWNER_EMAIL", "owner_email", "EMAIL", "email"):
        raw = _strip_str(props.get(k))
        if raw and "@" in raw:
            return raw
    return None


def _is_washington_county(county_fips: str) -> bool:
    cf = (county_fips or "").strip()
    return len(cf) == 5 and cf.startswith(_WA_STATE_FIPS_PREFIX)


def build_manual_research_checklist(
    *,
    county_fips: str,
    primary: OwnerCandidate | None,
) -> list[str]:
    """Human-only diligence prompts (county recorder, SOS, related parcels). No automated scraping."""
    lines: list[str] = [
        f"County recorder / auditor ({county_fips}): confirm grantee matches recorded owner and note deed exceptions.",
        "Assessor vs tax bill mailing: verify current billing contact if different from legal owner.",
    ]
    if primary is None or primary.kind == OwnerKind.unknown:
        lines.append("Resolve owner from full assessor roll export or title-grade vendor before outreach.")
        return lines
    if primary.kind == OwnerKind.entity:
        lines.extend(
            [
                "Secretary of State (entity): confirm good standing, registered agent, and governors/managers.",
                "Related parcels: search county GIS / tax portal for same mailing address or parent LLC.",
                "News / litigation: lightweight manual search for bankruptcies or land-use disputes (counsel-guided).",
            ]
        )
    else:
        lines.extend(
            [
                "Individual owner: confirm identity across recorder filings; treat OSINT hits as unverified leads.",
                "Privacy / consent: phone/email from third-party lists require vendor permissible purpose + counsel.",
            ]
        )
    return lines


def build_owner_outreach_brief(
    *,
    county_fips: str,
    apn: str,
    raw_properties: dict[str, Any] | None,
    owners: list[OwnerCandidate],
    owner_research_tier: Literal["basic", "standard", "deep"] = "standard",
    normalized_owner_key: str | None = None,
    registry_lookup: RegistryLookupSummary | None = None,
    vendor_lookup: VendorLookupSummary | None = None,
    same_owner_qualified_other_count: int | None = None,
    same_owner_peer_examples: list[str] | None = None,
) -> OwnerOutreachBrief:
    props = raw_properties or {}
    primary = owners[0] if owners else None
    if primary is None or primary.kind == OwnerKind.unknown:
        one_liner = "Unknown (no owner on roll)"
    else:
        one_liner = f"{primary.display_name} ({primary.kind.value}, conf={primary.confidence:.2f}, {primary.source})"

    mail = _mailing_from_props(props)
    situs = _situs_from_props(props)
    phone = _phone_from_props(props)
    email = _email_from_props(props)

    gaps: list[str] = []
    if not mail:
        gaps.append("No mailing address on ingest payload — pull from assessor full roll or vendor.")
    if not situs:
        gaps.append("No situs / property address on ingest payload — optional for site visit planning.")
    if primary and primary.kind == OwnerKind.entity and not mail:
        gaps.append("Entity owner without mail on file — SOS registered agent address is the usual path.")

    steps: list[OutreachStep] = []
    rank = 1
    tier_is_basic = owner_research_tier == "basic"

    if (
        not tier_is_basic
        and primary
        and primary.kind == OwnerKind.entity
        and _is_washington_county(county_fips)
    ):
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.secretary_of_state,
                title="Washington Secretary of State — business lookup",
                instruction=(
                    "Search the entity name on the WA SOS Corporations site to confirm status, "
                    "registered agent, and principal address before outreach."
                ),
                confidence=0.75,
                requires_human=True,
            )
        )
        rank += 1
    elif not tier_is_basic and primary and primary.kind == OwnerKind.entity:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.secretary_of_state,
                title="State business registry lookup",
                instruction=(
                    "Resolve the entity in the state of formation / qualification registry for "
                    "registered agent and good-standing before mail or phone outreach."
                ),
                confidence=0.55,
                requires_human=True,
            )
        )
        rank += 1

    if mail:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.certified_mail,
                title="Certified mail to mailing address on file",
                instruction=f"Use assessor / roll mailing: {mail}",
                confidence=0.7 if primary and primary.kind == OwnerKind.individual else 0.6,
                requires_human=True,
            )
        )
        rank += 1

    if email:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.email,
                title="Email (only if verified against roll or counsel-approved list)",
                instruction=f"Address on file: {email}",
                confidence=0.45,
                requires_human=True,
            )
        )
        rank += 1

    if phone:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.phone,
                title="Phone outreach (manual, consent-aware)",
                instruction=(
                    f"Number on file: {phone}. Confirm still tied to owner; "
                    "follow TCPA / internal counsel policy."
                ),
                confidence=0.4,
                requires_human=True,
            )
        )
        rank += 1

    if situs and (not mail or (mail and situs.strip().lower() != mail.strip().lower())):
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.site_visit,
                title="Property / situs visit or door notice (if policy allows)",
                instruction=f"Situs from ingest: {situs}. Use only with legal guidance and local solicitation rules.",
                confidence=0.35,
                requires_human=True,
            )
        )
        rank += 1

    if not tier_is_basic:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.vendor_research,
                title="Licensed skip-trace / data vendor (production)",
                instruction="When roll fields are incomplete, use an approved vendor chain-of-custody workflow.",
                confidence=0.5,
                requires_human=True,
            )
        )

    compliance = [
        "Counsel must approve templates and channels before any outbound contact.",
        "Do not automate calls or texts without an explicit compliance review.",
        "Automated owner enrichment must follow vendor contracts and permitted-use policies.",
    ]

    if tier_is_basic:
        research = [
            f"County recorder / auditor ({county_fips}): confirm grantee matches recorded owner.",
            "Assessor vs tax bill mailing: verify current billing contact if different from legal owner.",
            "Deep owner lookup (SOS, portfolio peers, vendor) runs only when entitlement and strategic scores meet pilot floors.",
        ]
        gaps.append(
            "Owner research tier: basic — roll parse only until parcel qualifies on both entitlement and strategic scores."
        )
    else:
        research = build_manual_research_checklist(county_fips=county_fips, primary=primary)
    if (
        not tier_is_basic
        and same_owner_qualified_other_count
        and same_owner_qualified_other_count > 0
    ):
        gaps.append(
            f"Portfolio signal: {same_owner_qualified_other_count} other qualified parcel(s) share "
            "normalized_owner_key — validate before assuming common control."
        )

    return OwnerOutreachBrief(
        county_fips=county_fips,
        apn=apn,
        owner_research_tier=owner_research_tier,
        recorded_owner_one_liner=one_liner,
        mailing_address_guess=mail,
        situs_address_guess=situs,
        phone_guess=phone,
        email_guess=email,
        steps=steps,
        data_gaps=gaps,
        compliance_notes=compliance,
        registry_lookup=registry_lookup,
        vendor_lookup=vendor_lookup,
        normalized_owner_key=normalized_owner_key,
        same_owner_qualified_other_count=same_owner_qualified_other_count,
        same_owner_peer_examples=list(same_owner_peer_examples or []),
        manual_research_checklist=research,
        computed_at=datetime.now(tz=UTC),
    )

