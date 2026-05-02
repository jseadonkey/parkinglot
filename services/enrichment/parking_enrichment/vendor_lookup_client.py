"""Optional outbound webhook to a licensed contact-data vendor (configure via API settings)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from parking_core.models import VendorContactHint, VendorLookupSummary


def fetch_vendor_owner_enrichment(
    *,
    enabled: bool,
    url: str | None,
    api_key: str | None,
    parcel_id: str,
    county_fips: str,
    apn: str,
    owners: list[dict[str, Any]],
    timeout_s: float = 25.0,
) -> VendorLookupSummary:
    """POST JSON payload to ``OWNER_VENDOR_LOOKUP_URL`` when enabled.

    Expected response shape (flexible):

    .. code-block:: json

       {"contacts": [{"channel": "email", "value": "a@b.co", "label": "work"}]}
    """
    if not enabled:
        return VendorLookupSummary(provider="webhook", outcome="skipped_disabled")
    u = (url or "").strip()
    if not u:
        return VendorLookupSummary(provider="webhook", outcome="skipped_no_url")

    payload = {
        "parcel_id": parcel_id,
        "county_fips": county_fips,
        "apn": apn,
        "owners": owners,
    }
    headers = {"Content-Type": "application/json"}
    tok = (api_key or "").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        req = urllib.request.Request(
            u,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
            code = getattr(resp, "status", 200) or 200
        data = json.loads(raw_body) if raw_body.strip() else {}
        contacts_raw = data.get("contacts") if isinstance(data, dict) else None
        contacts: list[VendorContactHint] = []
        if isinstance(contacts_raw, list):
            for item in contacts_raw:
                if not isinstance(item, dict):
                    continue
                ch = str(item.get("channel") or "unknown")
                val = str(item.get("value") or "").strip()
                if not val:
                    continue
                contacts.append(
                    VendorContactHint(
                        channel=ch,
                        value=val,
                        label=str(item["label"]).strip() if item.get("label") else None,
                    )
                )
        notes = data.get("notes") if isinstance(data, dict) else None
        return VendorLookupSummary(
            provider=str(data.get("provider") or "webhook"),
            outcome="hit",
            http_status=int(code),
            notes=str(notes) if notes is not None else None,
            contacts=contacts,
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000]
        return VendorLookupSummary(
            provider="webhook",
            outcome="error",
            http_status=e.code,
            error_detail=body or str(e),
        )
    except Exception as e:
        return VendorLookupSummary(
            provider="webhook",
            outcome="error",
            error_detail=str(e)[:2000],
        )
