#!/usr/bin/env python3
"""Post admin UI smoke failures to Slack (optional CI step)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    report_path = os.environ.get("SMOKE_REPORT", "scripts/admin-ui-smoke/smoke-report.json")
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_DIGEST_CHANNEL_ID", "").strip()
    if not token or not channel:
        print("Skip Slack notify (SLACK_BOT_TOKEN or SLACK_DIGEST_CHANNEL_ID unset)")
        return 0

    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    except OSError as exc:
        print(f"No report at {report_path}: {exc}", file=sys.stderr)
        return 0

    issues = report.get("issues") or []
    if not issues:
        print("No issues in report — skip Slack")
        return 0

    lines = [
        ":warning: *Admin UI smoke failed* — browser agent found issues on vspecialist.com",
        f"Checked: {report.get('checked_at', '?')} · {report.get('base_url', '?')}",
        "",
    ]
    for item in issues[:15]:
        lines.append(f"• *{item.get('label', '?')}* (`{item.get('page', '?')}`): {item.get('detail', '?')}")
    if len(issues) > 15:
        lines.append(f"_…and {len(issues) - 15} more (see GitHub Actions artifact)_")

    payload = {
        "channel": channel,
        "text": "\n".join(lines),
        "unfurl_links": False,
    }
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        print(f"Slack post failed: {exc}", file=sys.stderr)
        return 1

    if not body.get("ok"):
        print(f"Slack API error: {body}", file=sys.stderr)
        return 1
    print("Posted smoke summary to Slack")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
