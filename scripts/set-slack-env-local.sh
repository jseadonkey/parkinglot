#!/usr/bin/env bash
# Merge SLACK_BOT_TOKEN + SLACK_DIGEST_CHANNEL_ID into repo-root .env for local docker compose.
#
#   export SLACK_BOT_TOKEN='xoxb-...'
#   export SLACK_DIGEST_CHANNEL_ID='C...'
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

python3 <<'PY'
import os
import pathlib

root = pathlib.Path.cwd()
env_path = root / ".env"
text = env_path.read_text(encoding="utf-8")
lines = [
    ln
    for ln in text.splitlines()
    if not ln.startswith("SLACK_BOT_TOKEN=") and not ln.startswith("SLACK_DIGEST_CHANNEL_ID=")
]
body = "\n".join(lines).rstrip() + "\n"
token = os.environ["TOKEN"]
chan = os.environ["CHAN"]
addition = (
    "\n# Slack — added by scripts/set-slack-env-local.sh\n"
    f"SLACK_BOT_TOKEN={token}\n"
    f"SLACK_DIGEST_CHANNEL_ID={chan}\n"
)
env_path.write_text(body + addition, encoding="utf-8", newline="\n")
print("Updated", env_path)
PY

echo "Next: docker compose up -d --build worker beat   # or full stack: docker compose up -d --build"
