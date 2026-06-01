"""Licensed contact vendor: BatchData skip-trace (preferred) or generic webhook."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from parking_core.models import VendorContactHint, VendorLookupSummary
from parking_enrichment.batchdata_skip_trace_client import fetch_batchdata_skip_trace


def fetch_vendor_owner_enrichment(
    *,
    enabled: bool,
    url: str | None,
    api_key: str | None,
    batchdata_api_key: str | None = None,
    parcel_id: str,
    county_fips: str,
    apn: str,
    owners: list[dict[str, Any]],
    raw_properties: dict[str, Any] | None = None,
    timeout_s: float = 25.0,
) -> VendorLookupSummary:
    """BatchData skip-trace when ``BATCHDATA_API_KEY`` is set; else generic webhook POST."""
    if not enabled:
        return VendorLookupSummary(provider="webhook", outcome="skipped_disabled")

    bd_key = (batchdata_api_key or "").strip()
    if bd_key:
        owner_name = None
        if owners:
            owner_name = str(owners[0].get("display_name") or "").strip() or None
        return fetch_batchdata_skip_trace(
            enabled=True,
            api_key=bd_key,
            parcel_id=parcel_id,
            county_fips=county_fips,
            apn=apn,
            raw_properties=raw_properties,
            owner_display_name=owner_name,
            timeout_s=max(timeout_s, 30.0),
        )

    u = (url or "").strip()
    if not u:
        return VendorLookupSummary(
            provider="webhook",
            outcome="skipped_no_url",
            notes="Set BATCHDATA_API_KEY or OWNER_VENDOR_LOOKUP_URL.",
        )

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
