#!/usr/bin/env python3
"""HTTP checks from GitHub Actions (internet path) — no SSH required."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime


def _get(url: str, timeout: float = 20.0) -> tuple[int, str, float]:
    started = time.perf_counter()
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "parking-site-watchdog/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            return resp.status, body, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body, (time.perf_counter() - started) * 1000
    except urllib.error.URLError as exc:
        return 0, str(exc.reason or exc), (time.perf_counter() - started) * 1000


def main() -> int:
    api_base = os.environ.get("PUBLIC_API_URL", "https://api.vspecialist.com").strip().rstrip("/")
    ui_base = os.environ.get("UI_SMOKE_BASE_URL", "https://vspecialist.com").strip().rstrip("/")
    out_path = os.environ.get("WATCHDOG_REPORT_PATH", "scripts/site-watchdog/external-checks.json")

    checks: list[dict] = []
    for path, name in (("/health", "api_health"), ("/ready", "api_ready")):
        status, body, ms = _get(f"{api_base}{path}")
        ok = status == 200 and '"status"' in body
        if path == "/ready":
            ok = ok and '"ready"' in body
        detail = f"HTTP {status}" if status else body[:200]
        checks.append(
            {"name": name, "ok": ok, "detail": detail, "latency_ms": round(ms, 1), "source": "github-external"}
        )

    op_url = f"{ui_base}/operator"
    status, body, ms = _get(op_url, timeout=25.0)
    ok = status in (200, 302, 307, 308) and status != 0
    if status == 200 and ("502 Bad Gateway" in body or "503 Service" in body):
        ok = False
        detail = "gateway error in HTML"
    else:
        detail = f"HTTP {status}" if status else body[:200]
    checks.append(
        {
            "name": "operator_ui",
            "ok": ok,
            "detail": f"{op_url} — {detail}",
            "latency_ms": round(ms, 1),
            "source": "github-external",
        }
    )

    failures = [c for c in checks if not c["ok"]]
    report = {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "runner": "github-external",
        "ok": len(failures) == 0,
        "failure_count": len(failures),
        "checks": checks,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"ok": report["ok"], "failure_count": report["failure_count"], "path": out_path}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
