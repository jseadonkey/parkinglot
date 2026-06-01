"""Collect all likely owner names, addresses, phones, and emails from every source."""

from __future__ import annotations

import re
from typing import Any

from app.db.models import OwnerCandidateRow
from app.owner_skip_trace import skip_trace_contacts_from_vendor
from parking_enrichment.owner_outreach_agent import (
    _email_from_props,
    _mailing_from_props,
    _phone_from_props,
    _situs_from_props,
)
from parking_enrichment.vendor_sources import vendor_provider_to_source

_CARE_OF_RE = re.compile(r"^(?:C/O|C/O\.|CARE OF)\s+(.+)$", re.I)


def _clean_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _norm_key(val: str) -> str:
    return re.sub(r"\s+", " ", val.strip().upper())


def _dedupe_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        val = _clean_str(item.get("value"))
        if not val:
            continue
        key = f"{item.get('kind', 'value')}:{_norm_key(val)}"
        if key in seen:
            continue
        seen.add(key)
        out.append({**item, "value": val})
    return out


def _append(
    items: list[dict[str, Any]],
    *,
    value: str | None,
    source: str,
    label: str | None = None,
    confidence: float | None = None,
    kind: str = "value",
) -> None:
    val = _clean_str(value)
    if not val:
        return
    items.append(
        {
            "value": val,
            "source": source,
            "label": label,
            "confidence": confidence,
            "kind": kind,
        }
    )


def _split_joint_owner_names(name: str) -> list[str]:
    """Split King County joint-owner strings like ``LAST A+LAST B``."""
    if "+" not in name:
        return [name]
    parts = [p.strip() for p in name.split("+") if p.strip()]
    if len(parts) <= 1:
        return [name]
    return parts


def _care_of_name(attn: str | None) -> str | None:
    if not attn:
        return None
    m = _CARE_OF_RE.match(attn.strip())
    if m:
        return m.group(1).strip()
    return None


def _join_kc_mailing(addr: str | None, cityst: str | None, z: str | None) -> str | None:
    line = _clean_str(addr)
    city = _clean_str(cityst)
    zip5 = _clean_str(z)
    if not line:
        return None
    tail = " ".join(x for x in (city, zip5) if x)
    return f"{line} {tail}".strip() if tail else line


def _join_situs(full: str | None, city: str | None, z: str | None, state: str = "WA") -> str | None:
    line = _clean_str(full)
    if not line:
        return None
    parts = [line]
    if city:
        parts.append(city.strip())
    if state or z:
        parts.append(" ".join(x for x in (state, z) if x))
    return ", ".join(parts) if len(parts) > 1 else line


def collect_name_candidates(
    *,
    block: dict[str, Any],
    brief: dict[str, Any],
    raw: dict[str, Any] | None,
    owners: list[OwnerCandidateRow],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    props = raw or {}

    taxpayer = _clean_str(block.get("taxpayer_name"))
    if taxpayer:
        _append(
            items,
            value=taxpayer,
            source=_clean_str(block.get("data_source")) or "owner_record",
            label="Tax account name",
            confidence=0.9,
            kind="name",
        )
        for part in _split_joint_owner_names(taxpayer):
            if part != taxpayer:
                _append(
                    items,
                    value=part,
                    source="owner_record_joint_split",
                    label="Joint owner (split from tax name)",
                    confidence=0.75,
                    kind="name",
                )

    attn = _clean_str(block.get("taxpayer_attn"))
    co = _care_of_name(attn)
    if co:
        _append(
            items,
            value=co,
            source="owner_record_attn",
            label="Care-of contact on tax account",
            confidence=0.8,
            kind="name",
        )
    elif attn and not re.search(r"P\.?\s*O\.?\s*BOX|PO BOX", attn, re.I):
        _append(
            items,
            value=attn,
            source="owner_record_attn",
            label="Attention line on tax account",
            confidence=0.7,
            kind="name",
        )

    for key in ("OWNER_NAME", "owner_name", "KCTP_NAME", "kctp_name"):
        val = _clean_str(props.get(key))
        if val:
            _append(
                items,
                value=val,
                source="assessor_roll",
                label="Assessor roll name",
                confidence=0.85,
                kind="name",
            )

    for oc in owners:
        dn = _clean_str(oc.display_name)
        if dn and dn.lower() != "unknown owner":
            _append(
                items,
                value=dn,
                source=_clean_str(oc.source) or "owner_candidates",
                label=f"Owner candidate ({oc.kind})",
                confidence=float(oc.confidence) if oc.confidence is not None else None,
                kind="name",
            )

    one_liner = _clean_str(brief.get("recorded_owner_one_liner"))
    if one_liner and not one_liner.lower().startswith("unknown"):
        _append(
            items,
            value=one_liner.split(" (")[0].strip(),
            source="outreach_brief",
            label="Outreach brief primary owner",
            confidence=0.7,
            kind="name",
        )

    registry = brief.get("registry_lookup")
    if isinstance(registry, dict):
        for key, label in (
            ("top_match_name", "SOS registry top match"),
            ("registered_agent_line", "SOS registered agent"),
        ):
            val = _clean_str(registry.get(key))
            if val:
                _append(
                    items,
                    value=val,
                    source=_clean_str(registry.get("provider")) or "registry",
                    label=label,
                    confidence=0.65,
                    kind="name",
                )

    for alias_key in ("ALIAS1", "ALIAS2", "alias1", "alias2"):
        val = _clean_str(props.get(alias_key))
        if val:
            _append(
                items,
                value=val,
                source="assessor_alias",
                label="Assessor alias name",
                confidence=0.6,
                kind="name",
            )

    return _dedupe_candidates(items)


def collect_mailing_address_candidates(
    *,
    block: dict[str, Any],
    brief: dict[str, Any],
    raw: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    props = raw or {}

    mail_block = _clean_str(block.get("mailing_address"))
    if mail_block:
        _append(
            items,
            value=mail_block,
            source=_clean_str(block.get("data_source")) or "owner_record",
            label="Tax account mailing",
            confidence=0.9,
            kind="mail",
        )

    kc_mail = _join_kc_mailing(
        _clean_str(block.get("kctp_addr")) or _clean_str(props.get("KCTP_ADDR")),
        _clean_str(block.get("kctp_cityst")) or _clean_str(props.get("KCTP_CTYST")),
        _clean_str(block.get("kctp_zip")) or _clean_str(props.get("KCTP_ZIP")),
    )
    if kc_mail:
        _append(
            items,
            value=kc_mail,
            source="king_county_assessor_gis",
            label="Tax account mailing (GIS parts)",
            confidence=0.88,
            kind="mail",
        )

    attn = _clean_str(block.get("taxpayer_attn")) or _clean_str(props.get("KCTP_ATTN"))
    if attn and re.search(r"P\.?\s*O\.?\s*BOX|PO BOX", attn, re.I):
        cityst = _clean_str(block.get("kctp_cityst")) or _clean_str(props.get("KCTP_CTYST"))
        zip5 = _clean_str(block.get("kctp_zip")) or _clean_str(props.get("KCTP_ZIP"))
        po_line = attn
        if cityst or zip5:
            po_line = f"{attn} {cityst or ''} {zip5 or ''}".strip()
        _append(
            items,
            value=po_line,
            source="owner_record_attn",
            label="PO box on tax account",
            confidence=0.75,
            kind="mail",
        )

    mail_guess = _clean_str(brief.get("mailing_address_guess"))
    if mail_guess:
        _append(
            items,
            value=mail_guess,
            source="outreach_brief",
            label="Outreach brief mailing guess",
            confidence=0.7,
            kind="mail",
        )

    mail_props = _mailing_from_props(props)
    if mail_props:
        _append(
            items,
            value=mail_props,
            source="assessor_roll",
            label="Assessor roll mailing",
            confidence=0.8,
            kind="mail",
        )

    registry = brief.get("registry_lookup")
    if isinstance(registry, dict):
        principal = _clean_str(registry.get("principal_address_line"))
        if principal:
            _append(
                items,
                value=principal,
                source=_clean_str(registry.get("provider")) or "registry",
                label="SOS principal / registry address",
                confidence=0.65,
                kind="mail",
            )
        agent_addr = _clean_str(registry.get("registered_agent_address"))
        if agent_addr:
            _append(
                items,
                value=agent_addr,
                source=_clean_str(registry.get("provider")) or "registry",
                label="SOS registered agent address",
                confidence=0.68,
                kind="mail",
            )

    return _dedupe_candidates(items)


def collect_situs_address_candidates(
    *,
    block: dict[str, Any],
    brief: dict[str, Any],
    raw: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    props = raw or {}

    situs_block = _clean_str(block.get("situs_address"))
    if situs_block:
        _append(
            items,
            value=situs_block,
            source=_clean_str(block.get("data_source")) or "owner_record",
            label="Property / situs address",
            confidence=0.9,
            kind="situs",
        )

    situs_gis = _join_situs(
        _clean_str(block.get("addr_full")) or _clean_str(props.get("ADDR_FULL")),
        _clean_str(block.get("situs_city")) or _clean_str(props.get("CTYNAME")) or _clean_str(props.get("POSTALCTYNAME")),
        _clean_str(block.get("situs_zip")) or _clean_str(props.get("ZIP5")),
    )
    if situs_gis:
        _append(
            items,
            value=situs_gis,
            source="king_county_assessor_gis",
            label="Property / situs address (GIS)",
            confidence=0.88,
            kind="situs",
        )

    situs_guess = _clean_str(brief.get("situs_address_guess"))
    if situs_guess:
        _append(
            items,
            value=situs_guess,
            source="outreach_brief",
            label="Outreach brief situs guess",
            confidence=0.7,
            kind="situs",
        )

    situs_props = _situs_from_props(props)
    if situs_props:
        _append(
            items,
            value=situs_props,
            source="assessor_roll",
            label="Assessor roll situs",
            confidence=0.8,
            kind="situs",
        )

    for label_key in (("SITUS_ADDRESS", "Assessor situs"), ("SUB_ADDRESS", "Sub / unit address")):
        val = _clean_str(props.get(label_key[0]))
        if val:
            _append(
                items,
                value=val,
                source="assessor_roll",
                label=label_key[1],
                confidence=0.75,
                kind="situs",
            )

    return _dedupe_candidates(items)


def collect_phone_email_contacts(
    *,
    brief: dict[str, Any],
    raw: dict[str, Any] | None,
    persons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    props = raw or {}

    phone = _clean_str(brief.get("phone_guess")) or _phone_from_props(props)
    if phone:
        _append(
            items,
            value=phone,
            source="outreach_brief" if brief.get("phone_guess") else "assessor_roll",
            label="Roll / brief phone",
            confidence=0.7,
            kind="phone",
        )

    email = _clean_str(brief.get("email_guess")) or _email_from_props(props)
    if email:
        _append(
            items,
            value=email,
            source="outreach_brief" if brief.get("email_guess") else "assessor_roll",
            label="Roll / brief email",
            confidence=0.7,
            kind="email",
        )

    vendor = brief.get("vendor_lookup")
    skip_trace_extra: list[dict[str, Any]] = []
    if isinstance(vendor, dict):
        skip_trace_extra.extend(skip_trace_contacts_from_vendor(vendor))
        if vendor_provider_to_source(_clean_str(vendor.get("provider"))) != "skip_trace":
            provider = _clean_str(vendor.get("provider")) or "vendor"
            for item in vendor.get("contacts") or []:
                if not isinstance(item, dict):
                    continue
                val = _clean_str(item.get("value"))
                if not val:
                    continue
                channel = (_clean_str(item.get("channel")) or "unknown").lower()
                skip_trace_extra.append(
                    {
                        "channel": channel,
                        "value": val,
                        "label": _clean_str(item.get("label")) or f"Vendor {channel}",
                        "source": provider,
                        "verified": False,
                    }
                )

    for person in persons:
        for field, kind in (("phone", "phone"), ("email", "email")):
            val = _clean_str(person.get(field))
            if val:
                _append(
                    items,
                    value=val,
                    source=_clean_str(person.get("source")) or "registry",
                    label=f"{person.get('role', 'contact')} {kind}",
                    confidence=0.65,
                    kind=kind,
                )

    # Normalize to contact dict shape expected by API/UI
    contacts: list[dict[str, Any]] = []
    for item in _dedupe_candidates(items):
        kind = item.get("kind") or "unknown"
        channel = item.get("channel") or ("mail" if kind == "mail" else kind)
        contacts.append(
            {
                "channel": channel,
                "value": item["value"],
                "label": item.get("label"),
                "source": item.get("source"),
                "verified": item.get("verified", False),
                "confidence": item.get("confidence"),
            }
        )
    return _merge_skip_trace_contacts(contacts, skip_trace_extra)


def _merge_skip_trace_contacts(
    base: list[dict[str, Any]], skip_trace: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Prefer skip-trace rows when the same phone/email appears from roll/brief."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in base:
        channel = (_clean_str(item.get("channel")) or "unknown").lower()
        value = _clean_str(item.get("value"))
        if value:
            by_key[(channel, value.upper())] = item
    for item in skip_trace:
        channel = (_clean_str(item.get("channel")) or "unknown").lower()
        value = _clean_str(item.get("value"))
        if value:
            by_key[(channel, value.upper())] = item
    return list(by_key.values())


def primary_from_candidates(candidates: list[dict[str, Any]]) -> str | None:
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda c: (float(c.get("confidence") or 0), len(c.get("value") or "")),
        reverse=True,
    )
    return ranked[0]["value"]
