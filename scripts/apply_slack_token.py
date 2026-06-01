#!/usr/bin/env python3
"""Merge SLACK_* into repo-root .env on the droplet and restart api, worker, beat."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
# Purveyors of Leisure — #gf-parkinglot-agents-chat (copy from Slack channel details if yours differs).
DEFAULT_CHANNEL = "C0B0VPSAH44"


def _drop_slack_assignment(line: str) -> bool:
    t = line.strip()
    if t.startswith("#"):
        t = t[1:].strip()
    return t.startswith("SLACK_BOT_TOKEN=") or t.startswith("SLACK_DIGEST_CHANNEL_ID=")


def main() -> int:
    token = ""
    if len(sys.argv) > 1:
        token = sys.argv[1].strip()
    token_file = ROOT / ".slack-bot-token"
    if not token and token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip()
        try:
            token_file.unlink()
        except OSError:
            pass
    if not token or not token.startswith("xoxb-"):
        print(
            "error: pass Bot User OAuth Token as argv1, or create a one-line "
            f"{token_file} file (chmod 600) then run with no args.",
            file=sys.stderr,
        )
        return 1

    chan = os.environ.get("SLACK_DIGEST_CHANNEL_ID", DEFAULT_CHANNEL).strip()

    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    lines: list[str] = []
    for line in text.splitlines():
        if "Optional Slack standup" in line and "docs/SLACK.md" in line:
            continue
        if _drop_slack_assignment(line):
            continue
        lines.append(line)
    body = "\n".join(lines).rstrip()
    block = (
        "\n\n# Slack — worker digests + API routes (docs/SLACK.md)\n"
        f"SLACK_BOT_TOKEN={token}\n"
        f"SLACK_DIGEST_CHANNEL_ID={chan}\n"
    )
    ENV_PATH.write_text(body + block, encoding="utf-8", newline="\n")
    os.chmod(ENV_PATH, 0o600)

    subprocess.run(
        ["docker", "compose", "up", "-d", "api", "worker", "beat"],
        cwd=str(ROOT),
        check=True,
    )
    print("Updated .env and restarted api, worker, beat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
