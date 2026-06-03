"""Lob.com certified-mail configuration and credential checks (no sending yet)."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from app.config import Settings

LOB_API_BASE = "https://api.lob.com/v1"


def lob_is_test_mode(api_key: str) -> bool:
    return (api_key or "").strip().startswith("test_")


def lob_from_name(settings: Settings) -> str:
    return (
        (settings.lob_from_name or "").strip()
        or (settings.outreach_sender_name or "").strip()
        or (settings.outreach_sender_company or "").strip()
    )


def lob_has_from_address(settings: Settings) -> bool:
    return bool(
        lob_from_name(settings)
        and (settings.lob_from_address_line1 or "").strip()
        and (settings.lob_from_address_city or "").strip()
        and (settings.lob_from_address_state or "").strip()
        and (settings.lob_from_address_zip or "").strip()
    )


def lob_configured(settings: Settings) -> bool:
    return bool((settings.lob_api_key or "").strip()) and lob_has_from_address(settings)


def verify_lob_api_key(api_key: str, *, timeout: float = 10.0) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "LOB_API_KEY is not set"
    url = f"{LOB_API_BASE}/addresses?limit=1"
    creds = base64.b64encode(f"{key}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return True, "ok"
            return False, f"unexpected status {resp.status}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        try:
            parsed = json.loads(body)
            message = parsed.get("error", {}).get("message") or body
        except json.JSONDecodeError:
            message = body
        return False, f"HTTP {exc.code}: {message}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)


def lob_status_payload(settings: Settings) -> dict[str, Any]:
    has_key = bool((settings.lob_api_key or "").strip())
    has_from = lob_has_from_address(settings)
    return {
        "lob_configured": lob_configured(settings),
        "has_api_key": has_key,
        "has_from_address": has_from,
        "lob_send_enabled": bool(settings.lob_send_enabled),
        "lob_test_mode": lob_is_test_mode(settings.lob_api_key) if has_key else None,
        "lob_mail_extra_service": (settings.lob_mail_extra_service or "certified").strip() or "certified",
    }
