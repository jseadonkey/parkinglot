#!/usr/bin/env python3
"""Slack summary for address-health-agent run."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def build_message(report: dict | None) -> str:
    run_url = os.environ.get("GITHUB_RUN_URL", "").strip()
    if not report:
        lines = [":warning: *Address health agent* — no report file"]
        if run_url:
            lines.append(f"<{run_url}|GitHub Actions run>")
        return "\n".join(lines)

    lines = [f"*Address health agent* · {report.get('checked_at', '?')}", ""]
    for row in report.get("counties") or []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"• {row.get('county_fips')}: {row.get('candidate_address_pct', '?')}% situs on "
            f"{row.get('candidate_pool', 0)} candidates ({row.get('candidate_gap', 0)} gaps)"
        )

    rotations = report.get("rotations") or []
    if rotations:
        lines.append("")
        lines.append(f":arrows_counterclockwise: *{len(rotations)} source rotation(s)*")
        for r in rotations[:6]:
            lines.append(f"• {r.get('county_fips')}: {r.get('from')} → {r.get('to')} ({r.get('reason')})")

    needs = [c for c in report.get("connector_runs") or [] if c.get("status") == "needs_new_source"]
    if needs:
        lines.append("")
        lines.append(":construction: *Chain exhausted — add catalog source + connector*")
        for n in needs[:4]:
            lines.append(f"• {n.get('county_fips')}: {n.get('detail', '')[:100]}")

    if run_url:
        lines.append(f"<{run_url}|GitHub Actions run>")
    return "\n".join(lines)


def _post(text: str) -> bool:
    api_base = os.environ.get("PUBLIC_API_URL", "https://api.vspecialist.com").strip().rstrip("/")
    key = os.environ.get("SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY", "").strip()
    if not key:
        return False
    payload = json.dumps({"text": text[:3900]}).encode()
    req = urllib.request.Request(
        f"{api_base}/internal/slack/test-message",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Internal-Key": key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return bool(json.loads(resp.read().decode()).get("ok"))
    except (urllib.error.URLError, json.JSONDecodeError):
        return False


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    snap = _load(root / "data" / "operator-agent" / "address-health-snapshot.json")
    text = build_message(snap)
    posted = _post(text)
    print(f"posted={posted}")
    return 0 if posted or not os.environ.get("SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
