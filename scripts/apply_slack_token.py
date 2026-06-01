#!/usr/bin/env python3
"""Merge SLACK_* into deploy/.env on the Droplet and restart api, worker, beat."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Production compose always loads deploy/.env (not repo-root .env).
ENV_PATH = ROOT / "deploy" / ".env"
FALLBACK_ENV = ROOT / ".env"
# Purveyors of Leisure — #gf-parkinglot-agents-chat (copy from Slack channel details if yours differs).
DEFAULT_CHANNEL = "C0B0VPSAH44"

COMPOSE_FILES = [
    "deploy/docker-compose.production.ghcr.yml",
    "deploy/docker-compose.production.yml",
]


def _drop_slack_assignment(line: str) -> bool:
    t = line.strip()
    if t.startswith("#"):
        t = t[1:].strip()
    return t.startswith("SLACK_BOT_TOKEN=") or t.startswith("SLACK_DIGEST_CHANNEL_ID=")


def _resolve_env_path() -> Path:
    if ENV_PATH.is_file():
        return ENV_PATH
    if FALLBACK_ENV.is_file():
        print(f"note: {ENV_PATH} missing; writing to {FALLBACK_ENV} (copy to deploy/.env for production)", file=sys.stderr)
        return FALLBACK_ENV
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    return ENV_PATH


def _compose_file() -> str:
    for rel in COMPOSE_FILES:
        if (ROOT / rel).is_file():
            return rel
    return COMPOSE_FILES[-1]


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
    env_path = _resolve_env_path()

    text = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
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
    env_path.write_text(body + block, encoding="utf-8", newline="\n")
    os.chmod(env_path, 0o600)

    compose = _compose_file()
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            compose,
            "--env-file",
            "deploy/.env" if (ROOT / "deploy" / ".env").is_file() else str(env_path.relative_to(ROOT)),
            "up",
            "-d",
            "--force-recreate",
            "api",
            "worker",
            "beat",
        ],
        cwd=str(ROOT),
        check=True,
    )
    print(f"Updated {env_path} and restarted api, worker, beat (compose: {compose}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
