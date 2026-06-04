#!/usr/bin/env bash
# Merge Slack channel settings into repo-root .env for local docker compose.
#
#   export SLACK_BOT_TOKEN='xoxb-...'
#   export SLACK_DIGEST_CHANNEL_ID='C...'
#   # optional, when these should differ from the digest channel:
#   export SLACK_AGENT_DISCUSSION_CHANNEL_ID='C...'
#   export SITE_WATCHDOG_SLACK_CHANNEL_ID='C...'
#   ./scripts/set-slack-env-local.sh
#   docker compose up -d --build worker beat
set -euo pipefail

: "${SLACK_BOT_TOKEN:?Set SLACK_BOT_TOKEN}"
: "${SLACK_DIGEST_CHANNEL_ID:?Set SLACK_DIGEST_CHANNEL_ID}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example"
  else
    echo "error: no .env and no .env.example in $ROOT" >&2
    exit 1
  fi
fi

export TOKEN="$SLACK_BOT_TOKEN"
export CHAN="$SLACK_DIGEST_CHANNEL_ID"
export AGENT_DISCUSSION_CHAN="${SLACK_AGENT_DISCUSSION_CHANNEL_ID:-}"
export WATCHDOG_CHAN="${SITE_WATCHDOG_SLACK_CHANNEL_ID:-}"

python3 <<'PY'
import os
import pathlib

root = pathlib.Path.cwd()
env_path = root / ".env"
text = env_path.read_text(encoding="utf-8")
updates = {
    "SLACK_BOT_TOKEN": os.environ["TOKEN"],
    "SLACK_DIGEST_CHANNEL_ID": os.environ["CHAN"],
}
optional = {
    "SLACK_AGENT_DISCUSSION_CHANNEL_ID": os.environ.get("AGENT_DISCUSSION_CHAN", "").strip(),
    "SITE_WATCHDOG_SLACK_CHANNEL_ID": os.environ.get("WATCHDOG_CHAN", "").strip(),
}
updates.update({key: val for key, val in optional.items() if val})
lines = [
    ln
    for ln in text.splitlines()
    if ln.split("=", 1)[0] not in updates
]
body = "\n".join(lines).rstrip() + "\n"
addition = "\n# Slack — added by scripts/set-slack-env-local.sh\n"
addition += "".join(f"{key}={val}\n" for key, val in updates.items())
env_path.write_text(body + addition, encoding="utf-8", newline="\n")
print("Updated", env_path)
PY

echo "Next: docker compose up -d --build worker worker-slack beat   # or full stack: docker compose up -d --build"
