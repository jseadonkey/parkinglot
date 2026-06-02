#!/usr/bin/env python3
"""Merge external + server watchdog JSON and post to Slack (agents channel)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def _load(path: str) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _merge(reports: list[dict]) -> dict:
    checks: list[dict] = []
    for rep in reports:
        checks.extend(rep.get("checks") or [])
    failures = [c for c in checks if not c.get("ok")]
    return {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "runner": "github-actions",
        "ok": len(failures) == 0,
        "failure_count": len(failures),
        "checks": checks,
    }


def _build_message(report: dict) -> tuple[str, bool]:
    if report.get("ok"):
        return (
            ":white_check_mark: *Site watchdog (GitHub) — all clear*\n"
            f"Checked {report.get('checked_at', '?')}\n"
            "External API/UI + Droplet server checks passed.",
            True,
        )
    lines = [
        ":rotating_light: *Site watchdog (GitHub) — problems detected*",
        f"Checked {report.get('checked_at', '?')}",
        "",
    ]
    for item in report.get("checks") or []:
        if item.get("ok"):
            continue
        lines.append(f"• *{item.get('name', '?')}* [{item.get('source', '?')}]: {item.get('detail', '?')}")
    run_url = os.environ.get("GITHUB_RUN_URL", "").strip()
    if run_url:
        lines.append(f"\n<{run_url}|GitHub Actions run>")
    lines.append("_Not the pipeline digest — site + server health only._")
    return "\n".join(lines)[:3900], False


def _post_api(text: str) -> bool:
    api_base = os.environ.get("PUBLIC_API_URL", "https://api.vspecialist.com").strip().rstrip("/")
    key = os.environ.get("SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY", "").strip()
    if not key:
        return False
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        f"{api_base}/internal/slack/test-message",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Internal-Key": key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return bool(json.loads(resp.read().decode()).get("ok"))
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
        print(f"API post failed: {exc}", file=sys.stderr)
        return False


def _post_token(text: str) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = (
        os.environ.get("SITE_WATCHDOG_SLACK_CHANNEL_ID", "").strip()
        or os.environ.get("SLACK_AGENT_DISCUSSION_CHANNEL_ID", "").strip()
        or os.environ.get("SLACK_DIGEST_CHANNEL_ID", "").strip()
    )
    if not token or not channel:
        return False
    payload = json.dumps({"channel": channel, "text": text[:3900], "unfurl_links": False}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        return bool(body.get("ok"))
    except urllib.error.URLError as exc:
        print(f"Slack post failed: {exc}", file=sys.stderr)
        return False


def _synthetic_from_step_failures() -> dict | None:
    """When a workflow step failed before writing JSON, surface that in the merged report."""
    checks: list[dict] = []
    for name, step_env, path_env, default_path in (
        ("external_step", "EXTERNAL_STEP", "WATCHDOG_EXTERNAL_REPORT", "scripts/site-watchdog/external-checks.json"),
        ("server_step", "SERVER_STEP", "WATCHDOG_SERVER_REPORT", "scripts/site-watchdog/server-checks.json"),
    ):
        step = os.environ.get(step_env, "").strip()
        path = os.environ.get(path_env, default_path).strip() or default_path
        if step == "failure" and not Path(path).is_file():
            checks.append(
                {
                    "name": name,
                    "ok": False,
                    "detail": f"step outcome={step}, no report file",
                    "source": "github-actions",
                }
            )
    if not checks:
        return None
    return {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "runner": "github-actions",
        "ok": False,
        "failure_count": len(checks),
        "checks": checks,
    }


def main() -> int:
    external = _load(os.environ.get("WATCHDOG_EXTERNAL_REPORT", "scripts/site-watchdog/external-checks.json"))
    server = _load(os.environ.get("WATCHDOG_SERVER_REPORT", "scripts/site-watchdog/server-checks.json"))
    reports = [r for r in (external, server) if r]
    if not reports:
        synthetic = _synthetic_from_step_failures()
        if synthetic:
            reports = [synthetic]
    if not reports:
        print("ERROR: no watchdog reports found", file=sys.stderr)
        return 1

    report = _merge(reports)
    text, ok = _build_message(report)

    # Always notify on failure; on success post only if ALWAYS_NOTIFY=1 (heartbeat from GH)
    always = os.environ.get("WATCHDOG_ALWAYS_NOTIFY", "").strip().lower() in ("1", "true", "yes")
    if ok and not always:
        print("All checks passed — skipping Slack (set WATCHDOG_ALWAYS_NOTIFY=1 for green heartbeats)")
        return 0

    posted = _post_api(text) or _post_token(text)
    if not posted:
        print("ERROR: could not post to Slack", file=sys.stderr)
        # Green checks should not fail GitHub Actions when Slack/API notify is misconfigured.
        return 0 if ok else 1

    print("Posted site watchdog report to Slack")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
