"""Assemble operator-facing owner / taxpayer record with enrichment ladder."""

from __future__ import annotations

from typing import Any

from app.db.models import OwnerCandidateRow, Parcel
from app.owner_candidate_collect import (
    collect_mailing_address_candidates,
    collect_name_candidates,
    collect_phone_email_contacts,
    collect_situs_address_candidates,
    primary_from_candidates,
)
from parking_enrichment.owner_classification import classify_owner_display_name, is_entity_name
from parking_enrichment.registry_lookup import registry_principals_as_persons, wa_ccfs_search_url_for_manual_review


def _clean_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _king_county_erealproperty_url(apn: str) -> str | None:
    if not apn or "-" not in apn:
        return None
    pin = apn.split("-")[-1].strip()
    if not pin:
        return None
    return f"https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx?ParcelNbr={pin}"


def _brief_block(parcel: Parcel) -> dict[str, Any]:
    b = parcel.owner_outreach_brief
    return b if isinstance(b, dict) else {}


def _owner_record_block(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    block = raw.get("owner_record")
    return block if isinstance(block, dict) else {}


def _contacts_from_brief(brief: dict[str, Any], mailing: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if mailing:
        out.append(
            {
                "channel": "mail",
                "value": mailing,
                "label": "Tax account mailing",
                "source": "king_county_assessor",
                "verified": False,
            }
        )
    phone = _clean_str(brief.get("phone_guess"))
    if phone:
        out.append(
            {
                "channel": "phone",
                "value": phone,
                "label": "Roll / vendor phone",
                "source": "outreach_brief",
                "verified": False,
            }
        )
    email = _clean_str(brief.get("email_guess"))
    if email:
        out.append(
            {
                "channel": "email",
                "value": email,
                "label": "Roll / vendor email",
                "source": "outreach_brief",
                "verified": False,
            }
        )
    vendor = brief.get("vendor_lookup")
    if isinstance(vendor, dict):
        for item in vendor.get("contacts") or []:
            if not isinstance(item, dict):
                continue
            val = _clean_str(item.get("value"))
            if not val:
                continue
            out.append(
                {
                    "channel": _clean_str(item.get("channel")) or "unknown",
                    "value": val,
                    "label": _clean_str(item.get("label")),
                    "source": _clean_str(vendor.get("provider")) or "vendor",
                    "verified": False,
                }
            )
    return out


def _persons_from_registry(brief: dict[str, Any]) -> list[dict[str, Any]]:
    registry = brief.get("registry_lookup")
    if not isinstance(registry, dict):
        return []
    return registry_principals_as_persons(registry)


def _merge_contacts(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for item in group:
            channel = (_clean_str(item.get("channel")) or "unknown").lower()
            value = _clean_str(item.get("value"))
            if not value:
                continue
            key = (channel, value.upper())
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def _enrichment_status(
    *,
    taxpayer: str | None,
    kind: str,
    mailing: str | None,
    contacts: list[dict[str, Any]],
    persons: list[dict[str, Any]],
    has_phone_or_email: bool,
) -> str:
    if not taxpayer:
        return "missing_taxpayer"
    if kind == "entity":
        if persons:
            if has_phone_or_email:
                return "entity_contacts_found"
            return "entity_principals_partial"
        if mailing:
            return "entity_mailing_only"
        return "entity_needs_sos"
    if has_phone_or_email and mailing:
        return "individual_contacts_partial"
    if mailing:
        return "individual_mailing_only"
    return "roll_only"


def _next_steps(
    *,
    kind: str,
    status: str,
    sos_url: str | None,
    tier: str | None,
) -> list[str]:
    steps: list[str] = []
    if kind == "entity":
        if status in ("entity_needs_sos", "entity_mailing_only", "entity_principals_partial"):
            if sos_url:
                steps.append("Open Washington SOS (CCFS) and confirm registered agent, governors, and principal address.")
            else:
                steps.append("Search the entity on the Washington Secretary of State business registry.")
            steps.append("Identify underlying decision-maker (manager, member, or trustee) before master-lease outreach.")
        if status == "entity_mailing_only":
            steps.append("Tax mailing may be a registered agent or CPA — verify who controls the property.")
    else:
        if status == "roll_only":
            steps.append("Pull full assessor roll or run licensed skip-trace for mailing, phone, and email.")
        elif status == "individual_mailing_only":
            steps.append("Consider vendor skip-trace for phone and email tied to the named individual.")
    if tier == "basic":
        steps.append("Full SOS / vendor enrichment runs when Atlas + Beacon dual-qualify this parcel.")
    if not steps:
        steps.append("Counsel review before any outbound call, text, or email.")
    return steps


def _enrichment_gaps(
    *,
    kind: str,
    status: str,
    mailing: str | None,
    has_phone: bool,
    has_email: bool,
    persons: list[dict[str, Any]],
) -> list[str]:
    gaps: list[str] = []
    if kind == "entity" and not persons:
        gaps.append("No registered agent or principal pulled yet — SOS lookup required for underlying person.")
    if not mailing:
        gaps.append("No mailing address on tax account.")
    if not has_phone:
        gaps.append("No phone number on file yet.")
    if not has_email:
        gaps.append("No email address on file yet.")
    if kind == "entity" and status == "entity_mailing_only":
        gaps.append("Entity mail may not reach the property decision-maker.")
    return gaps


def build_owner_record_view(
    parcel: Parcel,
    owners: list[OwnerCandidateRow],
) -> dict[str, Any]:
    raw = parcel.raw_properties if isinstance(parcel.raw_properties, dict) else None
    block = _owner_record_block(raw)
    brief = _brief_block(parcel)

    name_candidates = collect_name_candidates(block=block, brief=brief, raw=raw, owners=owners)
    mailing_candidates = collect_mailing_address_candidates(block=block, brief=brief, raw=raw)
    situs_candidates = collect_situs_address_candidates(block=block, brief=brief, raw=raw)

    taxpayer = primary_from_candidates(name_candidates)
    kind_enum = classify_owner_display_name(taxpayer)
    kind = kind_enum.value

    mailing = primary_from_candidates(mailing_candidates)
    situs = primary_from_candidates(situs_candidates)
    attn = _clean_str(block.get("taxpayer_attn"))

    land = block.get("appraised_land")
    impr = block.get("appraised_improvements")
    url = _clean_str(block.get("erealproperty_url"))
    if not url and parcel.county_fips == "53033":
        url = _king_county_erealproperty_url(parcel.apn)

    registry = brief.get("registry_lookup") if isinstance(brief.get("registry_lookup"), dict) else {}
    sos_url = _clean_str(registry.get("search_results_url")) or _clean_str(registry.get("detail_url"))
    if kind == "entity" and not sos_url and taxpayer:
        sos_url = wa_ccfs_search_url_for_manual_review(taxpayer)

    persons = _persons_from_registry(brief)
    extra_contacts = collect_phone_email_contacts(brief=brief, raw=raw, persons=persons)
    contacts = _merge_contacts(_contacts_from_brief(brief, mailing), extra_contacts)
    has_phone = any(c.get("channel") == "phone" for c in contacts)
    has_email = any(c.get("channel") == "email" for c in contacts)
    tier = _clean_str(brief.get("owner_research_tier"))

    status = _enrichment_status(
        taxpayer=taxpayer,
        kind=kind,
        mailing=mailing,
        contacts=contacts,
        persons=persons,
        has_phone_or_email=has_phone or has_email,
    )

    return {
        "taxpayer_name": taxpayer,
        "taxpayer_attn": attn,
        "mailing_address": mailing,
        "situs_address": situs,
        "appraised_land": float(land) if land is not None else None,
        "appraised_improvements": float(impr) if impr is not None else None,
        "property_type": _clean_str(block.get("property_type")),
        "erealproperty_url": url,
        "data_source": _clean_str(block.get("data_source")),
        "enriched_at": _clean_str(block.get("enriched_at")),
        "owner_kind": kind,
        "is_entity": is_entity_name(taxpayer),
        "enrichment_status": status,
        "sos_search_url": sos_url if kind == "entity" else None,
        "registered_agent": _clean_str(registry.get("registered_agent_line")),
        "registered_agent_address": _clean_str(registry.get("registered_agent_address")),
        "principal_address": _clean_str(registry.get("principal_address_line")),
        "underlying_persons": persons,
        "name_candidates": name_candidates,
        "mailing_address_candidates": mailing_candidates,
        "situs_address_candidates": situs_candidates,
        "contacts": contacts,
        "enrichment_gaps": _enrichment_gaps(
            kind=kind,
            status=status,
            mailing=mailing,
            has_phone=has_phone,
            has_email=has_email,
            persons=persons,
        ),
        "next_steps": _next_steps(kind=kind, status=status, sos_url=sos_url, tier=tier),
        "owner_research_tier": tier,
    }
