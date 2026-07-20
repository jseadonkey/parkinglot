"""BatchData property skip-trace — phone/email only (one billable property per call)."""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from parking_core.models import VendorContactHint, VendorLookupSummary

SKIP_TRACE_URL = "https://api.batchdata.com/api/v3/property/skip-trace"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_DEFAULT_STATE = "WA"
_MAX_PHONES = 2
_MAX_EMAILS = 2
# OSM usage policy: max 1 request/second (shared across Celery fork workers on one host).
_NOMINATIM_MIN_INTERVAL_S = 1.1
_NOMINATIM_LOCK_PATH = os.environ.get(
    "NOMINATIM_RATE_LOCK_PATH",
    "/tmp/parkinglot-nominatim.rate",
)

_STREET_CITY_STATE_ZIP = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?$",
    re.I,
)
_CITY_STATE_ZIP_TAIL = re.compile(
    r"^(?P<street>.+?)\s+(?P<city>[A-Z][A-Za-z .'-]+)\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?$"
)
_ZIP_ONLY = re.compile(r"^\d{5}(?:-\d{4})?$")
_STREET_HINT = re.compile(
    r"\b(ST|STREET|AVE|AVENUE|DR|DRIVE|RD|ROAD|BLVD|WAY|LN|LANE|CT|COURT|PL|PLACE|HWY)\b",
    re.I,
)
# OSM often returns trails/freeways for vacant downtown footprints — not property situs.
_NON_SITUS_ROAD = re.compile(
    r"\b(trail|freeway|railway|railroad|interurban|bike\s*path|footway)\b",
    re.I,
)
_REVERSE_ZOOMS = (18, 17, 16, 15)


def _strip_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _looks_like_street(value: str | None) -> bool:
    text = (value or "").strip()
    if not text or _ZIP_ONLY.match(text):
        return False
    if _NON_SITUS_ROAD.search(text):
        return False
    if re.search(r"\d", text):
        return True
    return bool(_STREET_HINT.search(text))


def _owner_record_block(raw: dict[str, Any]) -> dict[str, Any]:
    block = raw.get("owner_record")
    return block if isinstance(block, dict) else {}


def _wa_city_zip(raw: dict[str, Any]) -> tuple[str | None, str | None, str]:
    block = _owner_record_block(raw)
    city = _strip_str(
        block.get("situs_city")
        or raw.get("SITUS_CITY_NM")
        or raw.get("SITUS_CITY")
        or raw.get("situs_city")
        or raw.get("LOC_CITY")
    )
    state = (
        _strip_str(block.get("situs_state") or raw.get("SITUS_STATE") or raw.get("situs_state"))
        or _DEFAULT_STATE
    ).upper()
    zip_code = _strip_str(
        block.get("situs_zip")
        or raw.get("SITUS_ZIP_NR")
        or raw.get("SITUS_ZIP")
        or raw.get("situs_zip")
        or raw.get("ZIP5")
        or raw.get("zip")
    )
    return city, zip_code[:5] if zip_code else None, state


def _street_candidates(raw: dict[str, Any]) -> list[str]:
    block = _owner_record_block(raw)
    candidates = [
        block.get("addr_full"),
        block.get("situs_street"),
        block.get("situs_address"),
        raw.get("ADDR_FULL"),
        raw.get("addr_full"),
        raw.get("FULLADDR"),
        raw.get("fulladdr"),
        raw.get("SITUS_LINE1"),
        raw.get("situs_line1"),
        raw.get("LOC_STREET"),
        raw.get("SITUS_ADDRESS"),
        raw.get("situs_address"),
        raw.get("SITUS_ADDR"),
        raw.get("situs_addr"),
        raw.get("PROPERTY_ADDRESS"),
        raw.get("property_address"),
        raw.get("SUB_ADDRESS"),
        raw.get("sub_address"),
    ]
    out: list[str] = []
    for item in candidates:
        text = _strip_str(item)
        if text and _looks_like_street(text):
            out.append(text)
    return out


def _structured_address(raw: dict[str, Any]) -> dict[str, str] | None:
    """Prefer structured situs fields from assessor / WaTech / owner_record."""
    city, zip_code, state = _wa_city_zip(raw)
    for street in _street_candidates(raw):
        if city and zip_code:
            return {"street": street, "city": city, "state": state, "zip": zip_code}
        parsed = _parse_freeform_address(street)
        if parsed:
            return parsed
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


def _wait_for_nominatim_slot() -> None:
    """Serialize Nominatim calls process-wide (fcntl) and enforce >=1.1s between requests."""
    lock_dir = os.path.dirname(_NOMINATIM_LOCK_PATH)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    with open(_NOMINATIM_LOCK_PATH, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            lock_file.seek(0)
            raw = lock_file.read().strip()
            last_at = float(raw) if raw else 0.0
            wait = _NOMINATIM_MIN_INTERVAL_S - (time.monotonic() - last_at)
            if wait > 0:
                time.sleep(wait)
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"{time.monotonic():.6f}")
            lock_file.flush()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def reverse_geocode_street(
    lat: float,
    lon: float,
    *,
    timeout_s: float = 12.0,
) -> dict[str, str] | None:
    """Best-effort street line from parcel centroid (Nominatim; rate-limited).

    Tries several zoom levels because vacant / park-adjacent footprints often reverse
    to trails at zoom 18 but to a nearby named street at 16–17.
    """
    for zoom in _REVERSE_ZOOMS:
        _wait_for_nominatim_slot()
        params = urllib.parse.urlencode(
            {
                "lat": f"{lat:.6f}",
                "lon": f"{lon:.6f}",
                "format": "json",
                "addressdetails": "1",
                "zoom": str(zoom),
            }
        )
        url = f"{NOMINATIM_REVERSE_URL}?{params}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "parkinglot-skip-trace/1.0 (property situs backfill)"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            continue

        address = data.get("address") if isinstance(data, dict) else None
        if not isinstance(address, dict):
            continue

        house = _strip_str(address.get("house_number"))
        road = _strip_str(
            address.get("road")
            or address.get("pedestrian")
            or address.get("residential")
            or address.get("footway")
        )
        if house and road:
            street_line = f"{house} {road}"
        else:
            street_line = road or house
        if not _looks_like_street(street_line):
            continue

        city = _strip_str(
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("hamlet")
            or address.get("municipality")
            or address.get("county")
        )
        state = _strip_str(address.get("state_code") or address.get("state")) or _DEFAULT_STATE
        if state and len(state) > 2:
            # Nominatim may return "Washington" — map common case.
            state = "WA" if state.lower() == "washington" else state[:2]
        zip_code = _strip_str(address.get("postcode"))
        if not city or not zip_code:
            continue
        return {
            "street": street_line,
            "city": city,
            "state": state.upper()[:2],
            "zip": zip_code[:5],
        }
    return None


def has_assessor_property_address(raw_properties: dict[str, Any] | None) -> bool:
    """True when county roll already has a usable street (no centroid geocode needed)."""
    return _structured_address(raw_properties or {}) is not None


def property_address_for_skip_trace(
    raw_properties: dict[str, Any] | None,
    *,
    centroid_lat_lon: tuple[float, float] | None = None,
    allow_centroid_geocode: bool = True,
) -> dict[str, str] | None:
    """Resolve situs / property address for BatchData (skip trace bills per property)."""
    raw = raw_properties or {}
    structured = _structured_address(raw)
    if structured:
        return structured

    if not allow_centroid_geocode or centroid_lat_lon is None:
        return None

    assessor_city, assessor_zip, assessor_state = _wa_city_zip(raw)
    lat, lon = centroid_lat_lon
    geocoded = reverse_geocode_street(lat, lon)
    if not geocoded:
        return None
    street = _strip_str(geocoded.get("street"))
    if not street:
        return None
    # Prefer assessor city/ZIP when present; otherwise use Nominatim (ZIP-only rolls).
    city = assessor_city or _strip_str(geocoded.get("city"))
    zip_code = assessor_zip or _strip_str(geocoded.get("zip"))
    state = (assessor_state or _strip_str(geocoded.get("state")) or _DEFAULT_STATE).upper()[:2]
    if not city or not zip_code:
        return None
    return {"street": street, "city": city, "state": state, "zip": zip_code[:5]}


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
    """Avoid a Skip Tracing V3 call when the assessor roll already has both channels."""
    from parking_enrichment.owner_outreach_agent import _emails_from_props, _phones_from_props

    props = raw_properties or {}
    if _phones_from_props(props) and _emails_from_props(props):
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
                label=" · ".join(label_parts) if label_parts else "BatchData phone",
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
            contacts.append(VendorContactHint(channel="email", value=email, label="BatchData email"))
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
    centroid_lat_lon: tuple[float, float] | None = None,
    resolved_property_address: dict[str, str] | None = None,
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

    skip_reason = should_skip_skip_trace(raw_properties)
    if skip_reason:
        return VendorLookupSummary(
            provider="batchdata",
            outcome="skipped_tier",
            notes=skip_reason,
        )

    addr = resolved_property_address or property_address_for_skip_trace(
        raw_properties,
        centroid_lat_lon=centroid_lat_lon,
    )
    if not addr:
        return VendorLookupSummary(
            provider="batchdata",
            outcome="error",
            error_detail=(
                "No situs / property address on parcel — skip trace requires "
                "property street, city, state, zip."
            ),
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
