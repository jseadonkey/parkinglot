#!/usr/bin/env python3
"""Post operator admin agent results to Slack (agents channel)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load(path: str) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _runner_error() -> str | None:
    explicit = os.environ.get("AGENT_RUNNER_ERROR", "").strip()
    if explicit:
        return explicit
    preflight = os.environ.get("AGENT_PREFLIGHT_OUTCOME", "")
    install = os.environ.get("AGENT_INSTALL_OUTCOME", "")
    test = os.environ.get("AGENT_TEST_OUTCOME", "")
    if preflight == "failure":
        return os.environ.get("AGENT_PREFLIGHT_ERROR", "Preflight failed")
    if install == "failure":
        return "Could not install Playwright dependencies"
    report_path = os.environ.get("AGENT_REPORT", "scripts/operator-admin-agent/agent-report.json")
    if test == "failure" and not _load(report_path):
        return "Browser agent crashed or timed out (see GitHub log)"
    return None


def _build_message(report: dict | None, remediation: dict | None) -> tuple[str, str]:
    run_url = os.environ.get("GITHUB_RUN_URL", "").strip()
    base = os.environ.get("UI_SMOKE_BASE_URL", "https://vspecialist.com").strip()
    runner_err = _runner_error()
    issues = (report or {}).get("issues") or []
    stagnation = (report or remediation or {}).get("stagnation") or []
    actions = (remediation or report or {}).get("remediation") or []
    metrics = (report or {}).get("metrics") or {}

    if runner_err and not issues:
        lines = [
            ":rotating_light: *Operator admin agent — could not run*",
            runner_err,
            f"Site: {base}",
        ]
        if run_url:
            lines.append(f"<{run_url}|GitHub Actions run>")
        return "runner_failed", "\n".join(lines)

    checked = (report or {}).get("checked_at", "?")
    lines = [f"*Operator admin agent* · {checked} · {base}", ""]

    if metrics:
        lines.append(
            f"Metrics: score_gaps={metrics.get('score_gaps', '?')} · "
            f"high_value={metrics.get('high_value_remaining', '?')} · "
            f"governor={metrics.get('load_governor_level', '?')} · "
            f"deals_failed={metrics.get('deals_failed', '?')}"
        )
        counties_loaded = metrics.get("counties_with_data")
        pilot_total = metrics.get("pilot_county_count")
        if counties_loaded is not None and pilot_total is not None:
            lines.append(
                f"Counties ingested: {counties_loaded}/{pilot_total} · "
                f"zero-grab={metrics.get('counties_zero_grab_count', '?')} · "
                f"WA remaining={metrics.get('wa_counties_remaining', '?')}"
            )
        if metrics.get("backlog_complete"):
            lines.append("Backlog: high-value work complete — county rollout can advance.")
        if metrics.get("should_advance_counties"):
            next_fips = metrics.get("wa_next_county_fips") or "?"
            lines.append(f"County rollout: nudging next WA county ({next_fips}).")

    scrape_gaps = (report or {}).get("scrape_gaps") or metrics.get("scrape_gaps") or []
    urgent_gaps = [
        g
        for g in scrape_gaps
        if isinstance(g, dict) and g.get("kind") in ("pilot_priority", "wa_rollout_next")
    ]
    if urgent_gaps:
        lines.append(f":earth_americas: *{len(urgent_gaps)} county scrape gap(s) (0 parcels)*")
        for g in urgent_gaps[:8]:
            lines.append(
                f"• {g.get('county_name', '?')} ({g.get('county_fips', '?')}): "
                f"{str(g.get('kind', '')).replace('_', ' ')}"
            )
        lines.append("")

    blocking = [
        i for i in issues if isinstance(i, dict) and i.get("severity") != "warning"
    ]
    warnings = [i for i in issues if isinstance(i, dict) and i.get("severity") == "warning"]

    if blocking:
        lines.append(f":warning: *{len(blocking)} UI issue(s)*")
        for item in blocking[:10]:
            lines.append(f"• *{item.get('label', '?')}*: {item.get('detail', '?')[:120]}")
        if len(blocking) > 10:
            lines.append(f"_…and {len(blocking) - 10} more_")
        lines.append("")
    elif warnings:
        lines.append(f":information_source: *{len(warnings)} scrape warning(s)* (pages OK)")
        for item in warnings[:6]:
            lines.append(f"• {item.get('detail', '?')[:120]}")
        lines.append("")

    if stagnation:
        lines.append(f":chart_with_downwards_trend: *{len(stagnation)} stagnant metric(s)* (>24h)")
        for s in stagnation[:6]:
            lines.append(f"• {s.get('metric')}: {s.get('previous')} → {s.get('current')} ({s.get('detail', '')[:80]})")
        lines.append("")

    if actions:
        lines.append("*Auto-fix applied:*")
        for a in actions:
            lines.append(f"• {a.get('action')}: {a.get('status')} — {str(a.get('detail', ''))[:80]}")
        lines.append("")

    if not blocking and not stagnation and not urgent_gaps:
        lines.insert(0, ":white_check_mark: *Operator admin agent — all clear*")
        lines.append("All operator pages loaded; metrics progressing or within window.")
    elif not blocking:
        lines.insert(0, ":large_yellow_circle: *Operator pages OK — follow-up applied*")

    if run_url:
        lines.append(f"<{run_url}|GitHub Actions run>")

    kind = "ok"
    if runner_err:
        kind = "runner_failed"
    elif blocking:
        kind = "issues_found"
    elif stagnation or urgent_gaps:
        kind = "stagnation"
    return kind, "\n".join(lines)


def _post(text: str) -> bool:
    api_base = os.environ.get("PUBLIC_API_URL", "https://api.vspecialist.com").strip().rstrip("/")
    key = os.environ.get("SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY", "").strip()
    if key:
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
            if body.get("ok"):
                return True
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            print(f"API notify failed: {exc}", file=sys.stderr)

    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_DIGEST_CHANNEL_ID", "").strip()
    if not token or not channel:
        return False
    payload = json.dumps({"channel": channel, "text": text[:3900], "unfurl_links": False}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return bool(json.loads(resp.read().decode()).get("ok"))
    except urllib.error.URLError:
        return False


def main() -> int:
    report_path = os.environ.get("AGENT_REPORT", "scripts/operator-admin-agent/agent-report.json")
    rem_path = os.environ.get("AGENT_REMEDIATION", "scripts/operator-admin-agent/agent-remediation.json")
    report = _load(report_path)
    remediation = _load(rem_path) or report
    kind, text = _build_message(report, remediation)
    posted = _post(text)
    if not posted:
        print("WARNING: Slack notify failed", file=sys.stderr)
    print(f"Report kind={kind} posted={posted}")
    if kind in ("runner_failed", "issues_found"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
