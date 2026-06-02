#!/usr/bin/env python3
"""Post admin UI smoke results to Slack (agents channel) — always, including runner failures."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _load_report(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def _runner_error() -> str | None:
    explicit = os.environ.get("SMOKE_RUNNER_ERROR", "").strip()
    if explicit:
        return explicit
    preflight = os.environ.get("SMOKE_PREFLIGHT_OUTCOME", "")
    install = os.environ.get("SMOKE_INSTALL_OUTCOME", "")
    smoke = os.environ.get("SMOKE_TEST_OUTCOME", "")
    preflight_err = os.environ.get("SMOKE_PREFLIGHT_ERROR", "").strip()
    if preflight == "failure":
        return preflight_err or "Preflight failed (check GitHub secrets UI_SMOKE_ADMIN_*)"
    if preflight == "skipped":
        return "Preflight did not run"
    if install == "failure":
        return "Could not install Playwright or npm dependencies"
    if install == "skipped":
        return "Install skipped after preflight failure"
    if smoke == "skipped":
        return "Smoke test skipped (install or preflight failed)"
    if smoke == "failure":
        return None  # may be UI failures — use report
    return None


def _build_message(report: dict | None) -> tuple[str, str]:
    """Return (kind, slack_text) where kind is ok | ui_failed | runner_failed."""
    run_url = os.environ.get("GITHUB_RUN_URL", "").strip()
    base = os.environ.get("UI_SMOKE_BASE_URL", "https://vspecialist.com").strip()
    runner_err = _runner_error()
    smoke = os.environ.get("SMOKE_TEST_OUTCOME", "")
    issues = (report or {}).get("issues") or []

    if smoke == "failure" and not issues and not runner_err:
        runner_err = "Browser smoke tests failed (login error, timeout, or crash — see GitHub log)"

    if runner_err and not issues:
        lines = [
            ":rotating_light: *Admin UI smoke agent — could not run*",
            runner_err,
            f"Site: {base}",
        ]
        if run_url:
            lines.append(f"<{run_url}|GitHub Actions run>")
        lines.append("_Fix secrets or CI, then re-run. Forward this to Cursor agent if stuck._")
        return "runner_failed", "\n".join(lines)

    checked = (report or {}).get("checked_at", "?")

    if issues:
        lines = [
            ":warning: *Admin UI smoke agent — issues found*",
            f"Checked: {checked} · {base}",
            "",
        ]
        for item in issues[:15]:
            lines.append(
                f"• *{item.get('label', '?')}* (`{item.get('page', '?')}`): {item.get('detail', '?')}"
            )
        if len(issues) > 15:
            lines.append(f"_…and {len(issues) - 15} more (see Actions artifact admin-ui-smoke-report)_")
        if run_url:
            lines.append(f"\n<{run_url}|GitHub Actions run>")
        lines.append("_Forward to Cursor agent in parkinglot to fix._")
        return "ui_failed", "\n".join(lines)

    lines = [
        ":white_check_mark: *Admin UI smoke agent — all clear*",
        f"Checked: {checked} · {base}",
        "All admin pages loaded with no API or visible errors.",
    ]
    if run_url:
        lines.append(f"<{run_url}|GitHub Actions run>")
    return "ok", "\n".join(lines)


def _post_via_api(text: str) -> bool:
    api_base = os.environ.get("PUBLIC_API_URL", "https://api.vspecialist.com").strip().rstrip("/")
    key = os.environ.get("SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY", "").strip()
    if not key:
        return False
    payload = json.dumps({"text": text[:3900]}).encode()
    req = urllib.request.Request(
        f"{api_base}/internal/slack/test-message",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Internal-Key": key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode())
        return bool(body.get("ok"))
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
        print(f"API slack/test-message failed: {exc}", file=sys.stderr)
        return False


def _post_via_slack_token(text: str) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_DIGEST_CHANNEL_ID", "").strip()
    if not token or not channel:
        return False
    payload = json.dumps({"channel": channel, "text": text[:3900], "unfurl_links": False}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        if not body.get("ok"):
            print(f"Slack API error: {body}", file=sys.stderr)
            return False
        return True
    except urllib.error.URLError as exc:
        print(f"Slack post failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    report_path = os.environ.get("SMOKE_REPORT", "scripts/admin-ui-smoke/smoke-report.json")
    report = _load_report(report_path)
    kind, text = _build_message(report)

    # Runner failed but tests never wrote a report — still notify.
    if kind == "runner_failed" and report is None:
        pass

    posted = _post_via_api(text)
    if not posted:
        posted = _post_via_slack_token(text)

    if not posted:
        print(
            "WARNING: Could not notify Slack/agent channel. Set SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY "
            "(posts via api …/internal/slack/test-message) or SLACK_BOT_TOKEN + SLACK_DIGEST_CHANNEL_ID.",
            file=sys.stderr,
        )
        # Do not fail CI when only notification is missing — avoids GitHub failure emails.
        if kind == "ok":
            return 0
        return 1

    print(f"Posted smoke report to agents channel ({kind})")
    # Fail CI when UI issues or runner could not complete — so GitHub also emails you.
    if kind in ("ui_failed", "runner_failed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
