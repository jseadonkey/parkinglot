from __future__ import annotations

import re
from typing import Any

from parking_core.models import (
    OutreachChannel,
    OutreachStep,
    OwnerCandidate,
    OwnerKind,
    OwnerOutreachBrief,
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


def build_owner_outreach_brief(
    *,
    county_fips: str,
    apn: str,
    raw_properties: dict[str, Any] | None,
    owners: list[OwnerCandidate],
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

    if primary and primary.kind == OwnerKind.entity and _is_washington_county(county_fips):
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
    elif primary and primary.kind == OwnerKind.entity:
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
    ]

    return OwnerOutreachBrief(
        county_fips=county_fips,
        apn=apn,
        recorded_owner_one_liner=one_liner,
        mailing_address_guess=mail,
        situs_address_guess=situs,
        phone_guess=phone,
        email_guess=email,
        steps=steps,
        data_gaps=gaps,
        compliance_notes=compliance,
    )

