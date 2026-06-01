from __future__ import annotations

import re
from typing import Any

from datetime import UTC, datetime

from parking_core.models import (
    ContactKind,
    OutreachChannel,
    OutreachStep,
    OwnerCandidate,
    OwnerContactPoint,
    OwnerKind,
    OwnerOutreachBrief,
    RegistryLookupSummary,
    VendorLookupSummary,
)

_WA_STATE_FIPS_PREFIX = "53"
_LIST_SEP_RE = re.compile(r"[;,|\n]+")


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


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        v = raw.strip()
        if not v:
            continue
        key = v.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _values_from_props(
    props: dict[str, Any],
    *,
    single_keys: tuple[str, ...],
    list_keys: tuple[str, ...] = (),
    prefix_keys: tuple[str, ...] = (),
) -> list[str]:
    found: list[str] = []
    for k in single_keys:
        raw = props.get(k)
        if raw is None:
            continue
        if isinstance(raw, list | tuple):
            for item in raw:
                s = _strip_str(item)
                if s:
                    found.append(s)
            continue
        s = _strip_str(raw)
        if not s:
            continue
        if any(sep in s for sep in (";", "|", "\n")):
            found.extend(part.strip() for part in _LIST_SEP_RE.split(s) if part.strip())
        elif "," in s and "@" not in s and not any(ch.isdigit() for ch in s[:6]):
            found.extend(part.strip() for part in s.split(",") if part.strip())
        else:
            found.append(s)
    for k in list_keys:
        raw = props.get(k)
        if isinstance(raw, list | tuple):
            for item in raw:
                s = _strip_str(item)
                if s:
                    found.append(s)
    for base in prefix_keys:
        for key, raw in props.items():
            if not isinstance(key, str) or not key.upper().startswith(base.upper()):
                continue
            s = _strip_str(raw)
            if s:
                found.append(s)
    return _dedupe_preserve(found)


def _mailing_from_props(props: dict[str, Any]) -> list[str]:
    singles = _values_from_props(
        props,
        single_keys=(
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
        ),
        list_keys=("MAILING_ADDRESSES", "mailing_addresses", "OWNER_MAILINGS", "owner_mailings"),
        prefix_keys=("MAIL_ADDR_", "mail_addr_", "MAILING_", "mailing_"),
    )
    if singles:
        return singles
    line1 = _strip_str(props.get("MAIL_LINE1") or props.get("mail_line1") or props.get("MAIL_STREET"))
    line2 = _strip_str(props.get("MAIL_LINE2") or props.get("mail_line2"))
    city = _strip_str(props.get("MAIL_CITY") or props.get("mail_city"))
    state = _strip_str(props.get("MAIL_STATE") or props.get("mail_state"))
    z = _strip_str(props.get("MAIL_ZIP") or props.get("mail_zip") or props.get("ZIP"))
    joined = _join_address_parts(line1, line2, city, _join_address_parts(state, z) if state or z else None)
    return [joined] if joined else []


def _situs_from_props(props: dict[str, Any]) -> list[str]:
    singles = _values_from_props(
        props,
        single_keys=(
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
        ),
        list_keys=("SITUS_ADDRESSES", "situs_addresses", "PROPERTY_ADDRESSES", "property_addresses"),
        prefix_keys=("SITUS_ADDR_", "situs_addr_", "SITUS_", "situs_"),
    )
    if singles:
        return singles
    line1 = _strip_str(props.get("SITUS_LINE1") or props.get("situs_line1") or props.get("LOC_STREET"))
    city = _strip_str(props.get("SITUS_CITY") or props.get("situs_city") or props.get("LOC_CITY"))
    state = _strip_str(props.get("SITUS_STATE") or props.get("situs_state"))
    z = _strip_str(props.get("SITUS_ZIP") or props.get("situs_zip"))
    joined = _join_address_parts(line1, city, _join_address_parts(state, z) if state or z else None)
    return [joined] if joined else []


def _phones_from_props(props: dict[str, Any]) -> list[str]:
    raw_values = _values_from_props(
        props,
        single_keys=(
            "OWNER_PHONE",
            "owner_phone",
            "PHONE",
            "phone",
            "DAY_PHONE",
            "day_phone",
        ),
        list_keys=("PHONES", "phones", "OWNER_PHONES", "owner_phones"),
        prefix_keys=("PHONE_", "phone_", "OWNER_PHONE_", "owner_phone_"),
    )
    out: list[str] = []
    for raw in raw_values:
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 10 or raw:
            out.append(raw)
    return _dedupe_preserve(out)


def _emails_from_props(props: dict[str, Any]) -> list[str]:
    raw_values = _values_from_props(
        props,
        single_keys=("OWNER_EMAIL", "owner_email", "EMAIL", "email"),
        list_keys=("EMAILS", "emails", "OWNER_EMAILS", "owner_emails"),
        prefix_keys=("EMAIL_", "email_", "OWNER_EMAIL_", "owner_email_"),
    )
    return _dedupe_preserve([v for v in raw_values if "@" in v])


def _contact_points_from_props(props: dict[str, Any]) -> list[OwnerContactPoint]:
    points: list[OwnerContactPoint] = []
    for value in _mailing_from_props(props):
        points.append(
            OwnerContactPoint(
                kind=ContactKind.mailing_address,
                value=value,
                source="assessor_roll",
                confidence=0.65,
            )
        )
    for value in _situs_from_props(props):
        points.append(
            OwnerContactPoint(
                kind=ContactKind.situs_address,
                value=value,
                source="assessor_roll",
                confidence=0.6,
            )
        )
    for value in _phones_from_props(props):
        points.append(
            OwnerContactPoint(
                kind=ContactKind.phone,
                value=value,
                source="assessor_roll",
                confidence=0.45,
            )
        )
    for value in _emails_from_props(props):
        points.append(
            OwnerContactPoint(
                kind=ContactKind.email,
                value=value,
                source="assessor_roll",
                confidence=0.45,
            )
        )
    return points


def _first_of_kind(points: list[OwnerContactPoint], kind: ContactKind) -> str | None:
    for p in points:
        if p.kind == kind:
            return p.value
    return None


def _format_contact_list(values: list[str], *, limit: int = 6) -> str:
    if not values:
        return "(none on file)"
    shown = values[:limit]
    text = "; ".join(shown)
    if len(values) > limit:
        text += f"; … (+{len(values) - limit} more)"
    return text


def _is_washington_county(county_fips: str) -> bool:
    cf = (county_fips or "").strip()
    return len(cf) == 5 and cf.startswith(_WA_STATE_FIPS_PREFIX)


def build_manual_research_checklist(
    *,
    county_fips: str,
    primary: OwnerCandidate | None,
) -> list[str]:
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

    contact_points = _contact_points_from_props(props)
    mail_addrs = [p.value for p in contact_points if p.kind == ContactKind.mailing_address]
    situs_addrs = [p.value for p in contact_points if p.kind == ContactKind.situs_address]
    phones = [p.value for p in contact_points if p.kind == ContactKind.phone]
    emails = [p.value for p in contact_points if p.kind == ContactKind.email]

    gaps: list[str] = []
    if not mail_addrs:
        gaps.append("No mailing address on ingest payload — pull from assessor full roll or vendor.")
    if not situs_addrs:
        gaps.append("No situs / property address on ingest payload — optional for site visit planning.")
    if primary and primary.kind == OwnerKind.entity and not mail_addrs:
        gaps.append("Entity owner without mail on file — SOS registered agent address is the usual path.")
    if len(mail_addrs) > 1:
        gaps.append(f"{len(mail_addrs)} mailing addresses on file — verify which is current before certified mail.")
    if len(phones) > 1:
        gaps.append(f"{len(phones)} phone numbers on file — log each attempt separately.")
    if len(emails) > 1:
        gaps.append(f"{len(emails)} email addresses on file — log each attempt separately.")

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

    if mail_addrs:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.certified_mail,
                title="Certified mail to mailing address(es) on file",
                instruction=f"Mailing addresses: {_format_contact_list(mail_addrs)}",
                confidence=0.7 if primary and primary.kind == OwnerKind.individual else 0.6,
                requires_human=True,
            )
        )
        rank += 1

    if emails:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.email,
                title="Email (only if verified against roll or counsel-approved list)",
                instruction=f"Addresses on file: {_format_contact_list(emails)}",
                confidence=0.45,
                requires_human=True,
            )
        )
        rank += 1

    if phones:
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.phone,
                title="Phone outreach (manual, consent-aware)",
                instruction=(
                    f"Numbers on file: {_format_contact_list(phones)}. Confirm still tied to owner; "
                    "follow TCPA / internal counsel policy. Record result per number."
                ),
                confidence=0.4,
                requires_human=True,
            )
        )
        rank += 1

    if situs_addrs and (
        not mail_addrs
        or any(s.strip().lower() not in {m.strip().lower() for m in mail_addrs} for s in situs_addrs)
    ):
        steps.append(
            OutreachStep(
                rank=rank,
                channel=OutreachChannel.site_visit,
                title="Property / situs visit or door notice (if policy allows)",
                instruction=(
                    f"Situs from ingest: {_format_contact_list(situs_addrs)}. "
                    "Use only with legal guidance and local solicitation rules."
                ),
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
        "Log each outreach attempt against the specific email, phone, or postal address used.",
        "Automated owner enrichment must follow vendor contracts and permitted-use policies.",
    ]

    research = build_manual_research_checklist(county_fips=county_fips, primary=primary)
    if same_owner_qualified_other_count and same_owner_qualified_other_count > 0:
        gaps.append(
            f"Portfolio signal: {same_owner_qualified_other_count} other qualified parcel(s) share "
            "normalized_owner_key — validate before assuming common control."
        )

    return OwnerOutreachBrief(
        county_fips=county_fips,
        apn=apn,
        recorded_owner_one_liner=one_liner,
        contact_points=contact_points,
        mailing_address_guess=_first_of_kind(contact_points, ContactKind.mailing_address),
        situs_address_guess=_first_of_kind(contact_points, ContactKind.situs_address),
        phone_guess=_first_of_kind(contact_points, ContactKind.phone),
        email_guess=_first_of_kind(contact_points, ContactKind.email),
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
