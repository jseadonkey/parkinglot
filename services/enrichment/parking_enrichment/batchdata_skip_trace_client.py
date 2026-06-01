"""BatchData property skip-trace — phone/email only (one billable property per call)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from parking_core.models import VendorContactHint, VendorLookupSummary

SKIP_TRACE_URL = "https://api.batchdata.com/api/v3/property/skip-trace"
_DEFAULT_STATE = "WA"
_MAX_PHONES = 2
_MAX_EMAILS = 2

_STREET_CITY_STATE_ZIP = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?$",
    re.I,
)
_CITY_STATE_ZIP_TAIL = re.compile(
    r"^(?P<street>.+?)\s+(?P<city>[A-Z][A-Za-z .'-]+)\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?$"
)


def _strip_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _owner_record_block(raw: dict[str, Any]) -> dict[str, Any]:
    block = raw.get("owner_record")
    return block if isinstance(block, dict) else {}


def _structured_address(raw: dict[str, Any]) -> dict[str, str] | None:
    """Prefer structured situs fields from assessor / owner_record."""
    block = _owner_record_block(raw)
    street = _strip_str(
        block.get("addr_full")
        or block.get("situs_street")
        or raw.get("ADDR_FULL")
        or raw.get("addr_full")
        or raw.get("SITUS_LINE1")
        or raw.get("situs_line1")
        or raw.get("LOC_STREET")
    )
    city = _strip_str(
        block.get("situs_city")
        or raw.get("SITUS_CITY")
        or raw.get("situs_city")
        or raw.get("LOC_CITY")
    )
    state = _strip_str(block.get("situs_state") or raw.get("SITUS_STATE") or raw.get("situs_state")) or _DEFAULT_STATE
    zip_code = _strip_str(
        block.get("situs_zip")
        or raw.get("SITUS_ZIP")
        or raw.get("situs_zip")
        or raw.get("ZIP5")
        or raw.get("zip")
    )
    if street and city and zip_code:
        return {"street": street, "city": city, "state": state.upper(), "zip": zip_code[:5]}
    return None


def _parse_freeform_address(line: str) -> dict[str, str] | None:
    text = line.strip()
    if not text:
        return None
    m = _STREET_CITY_STATE_ZIP.match(text)
    if m:
        return {
            "street": m.group("street").strip(),
            "city": m.group("city").strip(),
            "state": m.group("state").upper(),
            "zip": m.group("zip")[:5],
        }
    m = _CITY_STATE_ZIP_TAIL.match(text)
    if m:
        return {
            "street": m.group("street").strip(),
            "city": m.group("city").strip(),
            "state": m.group("state").upper(),
            "zip": m.group("zip")[:5],
        }
    return None


def property_address_for_skip_trace(raw_properties: dict[str, Any] | None) -> dict[str, str] | None:
    """Resolve situs / property address for BatchData (skip trace bills per property)."""
    raw = raw_properties or {}
    structured = _structured_address(raw)
    if structured:
        return structured

    block = _owner_record_block(raw)
    for candidate in (
        _strip_str(block.get("situs_address")),
        _strip_str(raw.get("SITUS_ADDRESS")),
        _strip_str(raw.get("situs_address")),
        _strip_str(raw.get("SITUS_ADDR")),
        _strip_str(raw.get("situs_addr")),
        _strip_str(raw.get("PROPERTY_ADDRESS")),
        _strip_str(raw.get("property_address")),
    ):
        if candidate:
            parsed = _parse_freeform_address(candidate)
            if parsed:
                return parsed
    return None


def _norm_name(val: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", val.upper()).strip()


def _pick_person(persons: list[dict[str, Any]], owner_name: str | None) -> dict[str, Any] | None:
    if not persons:
        return None
    for person in persons:
        if person.get("propertyOwner") is True:
            return person
    target = _norm_name(owner_name or "")
    if target:
        for person in persons:
            full = _norm_name(str((person.get("name") or {}).get("full") or ""))
            if full and (full in target or target in full):
                return person
    return persons[0]


def should_skip_skip_trace(raw_properties: dict[str, Any] | None) -> str | None:
    """Avoid a $0.07 Skip Tracing V3 call when the assessor roll already has both channels."""
    from parking_enrichment.owner_outreach_agent import _email_from_props, _phone_from_props

    props = raw_properties or {}
    if _phone_from_props(props) and _email_from_props(props):
        return "Assessor roll already has phone and email — skip trace not billed."
    return None


def _format_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number


def _contacts_from_person(person: dict[str, Any]) -> list[VendorContactHint]:
    contacts: list[VendorContactHint] = []
    phones = person.get("phones") if isinstance(person.get("phones"), list) else []
    sorted_phones = sorted(
        (p for p in phones if isinstance(p, dict) and _strip_str(p.get("number"))),
        key=lambda p: (
            0 if str(p.get("type") or "").lower() == "mobile" else 1,
            int(p.get("rank") or 99),
        ),
    )
    for phone in sorted_phones[:_MAX_PHONES]:
        number = _strip_str(phone.get("number"))
        if not number:
            continue
        flags: list[str] = []
        if phone.get("dnc"):
            flags.append("DNC")
        if phone.get("tcpa"):
            flags.append("TCPA")
        ptype = _strip_str(phone.get("type"))
        label_parts = [ptype] if ptype else []
        if flags:
            label_parts.append(",".join(flags))
        contacts.append(
            VendorContactHint(
                channel="phone",
                value=_format_phone(number),
                label=" · ".join(["Skip trace", *label_parts]) if label_parts else "Skip trace phone",
            )
        )

    emails = person.get("emails") if isinstance(person.get("emails"), list) else []
    sorted_emails = sorted(
        (e for e in emails if isinstance(e, dict) and _strip_str(e.get("email"))),
        key=lambda e: int(e.get("rank") or 99),
    )
    for item in sorted_emails[:_MAX_EMAILS]:
        email = _strip_str(item.get("email"))
        if email:
            contacts.append(VendorContactHint(channel="email", value=email, label="Skip trace email"))
    return contacts


def fetch_batchdata_skip_trace(
    *,
    enabled: bool,
    api_key: str | None,
    parcel_id: str,
    county_fips: str,
    apn: str,
    raw_properties: dict[str, Any] | None,
    owner_display_name: str | None = None,
    timeout_s: float = 30.0,
) -> VendorLookupSummary:
    """One Skip Tracing V3 call — emails and phones only ($0.07/property on BatchData pricing)."""
    if not enabled:
        return VendorLookupSummary(provider="batchdata", outcome="skipped_disabled")
    tok = (api_key or "").strip()
    if not tok:
        return VendorLookupSummary(
            provider="batchdata",
            outcome="skipped_no_url",
            notes="BATCHDATA_API_KEY not configured.",
        )

    addr = property_address_for_skip_trace(raw_properties)
    if not addr:
        return VendorLookupSummary(
            provider="batchdata",
            outcome="error",
            error_detail="No situs / property address on parcel — skip trace requires property street, city, state, zip.",
        )

    payload = {
        "requests": [
            {
                "propertyAddress": {
                    "street": addr["street"],
                    "city": addr["city"],
                    "state": addr["state"],
                    "zip": addr["zip"],
                },
                "requestId": f"{county_fips}:{apn}",
            }
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {tok}",
    }

    try:
        req = urllib.request.Request(
            SKIP_TRACE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
            code = getattr(resp, "status", 200) or 200
        data = json.loads(raw_body) if raw_body.strip() else {}
        status = data.get("status") if isinstance(data, dict) else None
        if isinstance(status, dict) and int(status.get("code") or 200) >= 400:
            return VendorLookupSummary(
                provider="batchdata",
                outcome="error",
                http_status=int(status.get("code") or 500),
                error_detail=str(status.get("text") or raw_body)[:2000],
            )

        result = data.get("result") if isinstance(data, dict) else None
        rows = result.get("data") if isinstance(result, dict) else None
        row = rows[0] if isinstance(rows, list) and rows else {}
        persons_raw = row.get("persons") if isinstance(row, dict) else None
        persons = [p for p in persons_raw if isinstance(p, dict)] if isinstance(persons_raw, list) else []
        person = _pick_person(persons, owner_display_name)
        if not person:
            return VendorLookupSummary(
                provider="batchdata",
                outcome="error",
                http_status=int(code),
                notes="Skip trace returned no persons for this property address.",
            )

        contacts = _contacts_from_person(person)
        notes_parts: list[str] = []
        name = (person.get("name") or {}).get("full") if isinstance(person.get("name"), dict) else None
        if name:
            notes_parts.append(f"Matched person: {name}")
        if person.get("deceased"):
            notes_parts.append("Flagged deceased — verify before outreach.")
        if person.get("litigator"):
            notes_parts.append("Litigator flag — counsel review required.")
        if not contacts:
            notes_parts.append("Person found but no phone/email returned.")

        return VendorLookupSummary(
            provider="batchdata",
            outcome="hit" if contacts else "error",
            http_status=int(code),
            notes=" ".join(notes_parts) if notes_parts else None,
            contacts=contacts,
            matched_person_name=str(name).strip() if name else None,
            error_detail=None if contacts else "No phone or email in skip-trace response.",
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000]
        return VendorLookupSummary(
            provider="batchdata",
            outcome="error",
            http_status=e.code,
            error_detail=body or str(e),
        )
    except Exception as e:
        return VendorLookupSummary(
            provider="batchdata",
            outcome="error",
            error_detail=str(e)[:2000],
        )
