#!/usr/bin/env bash
# Step 3–4: merge Slack vars into remote deploy/.env and restart worker, worker-slack, and beat.
#
# From your laptop (SSH to the Droplet must work). Example:
#   export SLACK_BOT_TOKEN='xoxb-...'
#   export SLACK_DIGEST_CHANNEL_ID='C0B0VPSAH44'  # #gf-parkinglot-agents-chat
#   export COMPOSE_FILE='deploy/docker-compose.production.yml'   # optional
#   ./scripts/set-slack-env-on-droplet.sh
#
# GHCR example:
#   export COMPOSE_FILE='deploy/docker-compose.production.ghcr.yml'
#   ./scripts/set-slack-env-on-droplet.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/set-slack-env-on-droplet.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

: "${SLACK_BOT_TOKEN:?Set SLACK_BOT_TOKEN (xoxb-...)}"
SLACK_DIGEST_CHANNEL_ID="${SLACK_DIGEST_CHANNEL_ID:-C0B0VPSAH44}"
SLACK_ALLOWED_CHANNEL_IDS="${SLACK_ALLOWED_CHANNEL_IDS:-C0B0VPSAH44}"
if [[ "$SLACK_DIGEST_CHANNEL_ID" != "C0B0VPSAH44" ]]; then
  echo "error: this parkinglot repo only permits SLACK_DIGEST_CHANNEL_ID=C0B0VPSAH44 (#gf-parkinglot-agents-chat)" >&2
  exit 1
fi
SLACK_ALLOWED_CHANNEL_IDS_COMPACT="$(printf '%s' "$SLACK_ALLOWED_CHANNEL_IDS" | tr -d '[:space:]')"
if [[ "$SLACK_ALLOWED_CHANNEL_IDS_COMPACT" != "C0B0VPSAH44" ]]; then
  echo "error: this parkinglot repo only permits SLACK_ALLOWED_CHANNEL_IDS=C0B0VPSAH44" >&2
  exit 1
fi

COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.production.yml}"

ENC_TOKEN=$(printf '%s' "$SLACK_BOT_TOKEN" | base64 | tr -d '\n')
ENC_CHAN=$(printf '%s' "$SLACK_DIGEST_CHANNEL_ID" | base64 | tr -d '\n')
ENC_ALLOWED=$(printf '%s' "$SLACK_ALLOWED_CHANNEL_IDS_COMPACT" | base64 | tr -d '\n')

ssh "${SSH_USER}@${DROPLET}" \
  REMOTE_PATH="${REMOTE_PATH}" \
  COMPOSE_FILE="${COMPOSE_FILE}" \
  ENC_TOKEN="${ENC_TOKEN}" \
  ENC_CHAN="${ENC_CHAN}" \
  ENC_ALLOWED="${ENC_ALLOWED}" \
  bash -s <<'EOS'
set -euo pipefail
cd "$REMOTE_PATH"
test -f deploy/.env || {
  echo "error: $REMOTE_PATH/deploy/.env not found. Copy deploy/env.production.example to deploy/.env on the Droplet first." >&2
  exit 1
}

TOKEN=$(printf '%s' "$ENC_TOKEN" | base64 -d)
CHAN=$(printf '%s' "$ENC_CHAN" | base64 -d)
ALLOWED=$(printf '%s' "$ENC_ALLOWED" | base64 -d)
export TOKEN CHAN ALLOWED

python3 <<'PY'
import os
import pathlib

root = pathlib.Path.cwd()
env_path = root / "deploy" / ".env"
text = env_path.read_text(encoding="utf-8")
lines = [
    ln
    for ln in text.splitlines()
    if not ln.startswith("APP_PROJECT_ID=")
    and not ln.startswith("SLACK_BOT_TOKEN=")
    and not ln.startswith("SLACK_DIGEST_CHANNEL_ID=")
    and not ln.startswith("SLACK_ALLOWED_CHANNEL_IDS=")
]
body = "\n".join(lines).rstrip() + "\n"
token = os.environ["TOKEN"]
chan = os.environ["CHAN"]
addition = (
    "\n# Slack — configured by scripts/set-slack-env-on-droplet.sh\n"
    "APP_PROJECT_ID=parkinglot\n"
    f"SLACK_BOT_TOKEN={token}\n"
    f"SLACK_DIGEST_CHANNEL_ID={chan}\n"
    f"SLACK_ALLOWED_CHANNEL_IDS={os.environ['ALLOWED']}\n"
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
