#!/usr/bin/env bash
# Step 3–4: merge Slack vars into remote deploy/.env and restart worker, worker-slack, and beat.
#
# From your laptop (SSH to the Droplet must work). Example:
#   export SLACK_BOT_TOKEN='xoxb-...'
#   export SLACK_DIGEST_CHANNEL_ID='C01234...'
#   export DROPLET='203.0.113.10'
#   export COMPOSE_FILE='deploy/docker-compose.production.yml'   # optional
#   ./scripts/set-slack-env-on-droplet.sh
#
# GHCR example:
#   export COMPOSE_FILE='deploy/docker-compose.production.ghcr.yml'
#   ./scripts/set-slack-env-on-droplet.sh
set -euo pipefail

: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
: "${SLACK_BOT_TOKEN:?Set SLACK_BOT_TOKEN (xoxb-...)}"
: "${SLACK_DIGEST_CHANNEL_ID:?Set SLACK_DIGEST_CHANNEL_ID (e.g. C...)}"

REMOTE_PATH="${REMOTE_PATH:-/opt/parking-acquisition-agents}"
SSH_USER="${SSH_USER:-root}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.production.yml}"

ENC_TOKEN=$(printf '%s' "$SLACK_BOT_TOKEN" | base64 | tr -d '\n')
ENC_CHAN=$(printf '%s' "$SLACK_DIGEST_CHANNEL_ID" | base64 | tr -d '\n')

ssh "${SSH_USER}@${DROPLET}" \
  REMOTE_PATH="${REMOTE_PATH}" \
  COMPOSE_FILE="${COMPOSE_FILE}" \
  ENC_TOKEN="${ENC_TOKEN}" \
  ENC_CHAN="${ENC_CHAN}" \
  bash -s <<'EOS'
set -euo pipefail
cd "$REMOTE_PATH"
test -f deploy/.env || {
  echo "error: $REMOTE_PATH/deploy/.env not found. Copy deploy/env.production.example to deploy/.env on the Droplet first." >&2
  exit 1
}

TOKEN=$(printf '%s' "$ENC_TOKEN" | base64 -d)
CHAN=$(printf '%s' "$ENC_CHAN" | base64 -d)
export TOKEN CHAN

python3 <<'PY'
import os
import pathlib

root = pathlib.Path.cwd()
env_path = root / "deploy" / ".env"
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
    "\n# Slack — configured by scripts/set-slack-env-on-droplet.sh\n"
    f"SLACK_BOT_TOKEN={token}\n"
    f"SLACK_DIGEST_CHANNEL_ID={chan}\n"
)
env_path.write_text(body + addition, encoding="utf-8", newline="\n")
print("Updated", env_path, "with SLACK_* entries.")
PY

if [[ "$COMPOSE_FILE" == *ghcr* ]]; then
  docker compose -f "$COMPOSE_FILE" --env-file deploy/.env pull worker worker-slack beat
  docker compose -f "$COMPOSE_FILE" --env-file deploy/.env up -d worker worker-slack beat
else
  docker compose -f "$COMPOSE_FILE" --env-file deploy/.env up -d --build worker worker-slack beat
fi

docker compose -f "$COMPOSE_FILE" --env-file deploy/.env ps worker worker-slack beat
EOS

echo "Done. Wait for the next scheduled digest, or POST /internal/slack/digest-now to test."
