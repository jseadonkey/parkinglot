"""Skip-trace (BatchData) helpers for owner record assembly."""

from __future__ import annotations

import re
from typing import Any

from parking_enrichment.vendor_sources import SKIP_TRACE_SOURCE, vendor_provider_to_source

_MATCHED_PERSON_RE = re.compile(r"Matched person:\s*(.+?)(?:\.\s|$)", re.I)


def _clean_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def skip_trace_hit(vendor: dict[str, Any] | None) -> bool:
    if not isinstance(vendor, dict):
        return False
    if vendor.get("outcome") != "hit":
        return False
    return bool(vendor.get("contacts"))


def matched_person_from_vendor(vendor: dict[str, Any]) -> str | None:
    name = _clean_str(vendor.get("matched_person_name"))
    if name:
        return name
    notes = _clean_str(vendor.get("notes"))
    if notes:
        m = _MATCHED_PERSON_RE.search(notes)
        if m:
            return m.group(1).strip()
    return None


def skip_trace_contacts_from_vendor(vendor: dict[str, Any]) -> list[dict[str, Any]]:
    source = vendor_provider_to_source(_clean_str(vendor.get("provider")))
    if source != SKIP_TRACE_SOURCE:
        return []
    out: list[dict[str, Any]] = []
    for item in vendor.get("contacts") or []:
        if not isinstance(item, dict):
            continue
        val = _clean_str(item.get("value"))
        if not val:
            continue
        channel = (_clean_str(item.get("channel")) or "unknown").lower()
        label = _clean_str(item.get("label"))
        if label and not label.lower().startswith("skip trace"):
            label = f"Skip trace · {label}"
        elif not label:
            label = f"Skip trace · {channel}"
        out.append(
            {
                "channel": channel,
                "value": val,
                "label": label,
                "source": SKIP_TRACE_SOURCE,
                "verified": False,
            }
        )
    return out


def skip_trace_person_from_vendor(vendor: dict[str, Any]) -> dict[str, Any] | None:
    name = matched_person_from_vendor(vendor)
    contacts = skip_trace_contacts_from_vendor(vendor)
    if not name and not contacts:
        return None
    phone = next((c["value"] for c in contacts if c.get("channel") == "phone"), None)
    email = next((c["value"] for c in contacts if c.get("channel") == "email"), None)
    return {
        "name": name,
        "role": "skip_trace_match",
        "address": None,
        "phone": phone,
        "email": email,
        "source": SKIP_TRACE_SOURCE,
    }


def skip_trace_summary_from_brief(brief: dict[str, Any]) -> dict[str, Any] | None:
    vendor = brief.get("vendor_lookup")
    if not isinstance(vendor, dict) or not skip_trace_hit(vendor):
        return None
    contacts = skip_trace_contacts_from_vendor(vendor)
    if not contacts:
        return None
    return {
        "provider": _clean_str(vendor.get("provider")),
        "outcome": _clean_str(vendor.get("outcome")),
        "matched_person": matched_person_from_vendor(vendor),
        "notes": _clean_str(vendor.get("notes")),
        "contacts": contacts,
    }
