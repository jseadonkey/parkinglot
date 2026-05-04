#!/usr/bin/env bash
# Diagnose why Slack digests may not appear. Run on the Droplet from repo root.
# Does not require `make` (minimal Ubuntu images often lack it — run this script directly).
#
#   cd /opt/workspaces/parkinglot   # or your REMOTE_PATH
#   chmod +x scripts/slack_droplet_check.sh
#   ./scripts/slack_droplet_check.sh
#
# Optional: sudo apt install -y make   # then: make slack-droplet-check
#
# Optional:
#   COMPOSE_FILE=deploy/docker-compose.production.ghcr.yml
#   ENV_FILE=deploy/.env
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${COMPOSE_FILE:=deploy/docker-compose.production.yml}"
: "${ENV_FILE:=${ROOT}/deploy/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: $ENV_FILE" >&2
  exit 2
fi

DC=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

echo "=== 1) beat + worker running? ==="
"${DC[@]}" ps beat worker 2>&1 || true

echo
echo "=== 2) Worker has SLACK vars (set / missing only — no secrets printed) ==="
if "${DC[@]}" exec -T worker sh -c '
  z="${SLACK_BOT_TOKEN:-}"
  c="${SLACK_DIGEST_CHANNEL_ID:-}"
  if [ -n "$z" ]; then echo "SLACK_BOT_TOKEN: set (${#z} chars)"; else echo "SLACK_BOT_TOKEN: MISSING"; fi
  if [ -n "$c" ]; then echo "SLACK_DIGEST_CHANNEL_ID: set ($c)"; else echo "SLACK_DIGEST_CHANNEL_ID: MISSING"; fi
' 2>&1; then
  :
else
  echo "(exec worker failed — is the worker container up?)"
fi

echo
echo "=== 3) API reports Slack configured? (needs PUBLIC_API_URL + INTERNAL_API_KEY in shell) ==="
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
BASE="${PUBLIC_API_URL:-}"
KEY="${INTERNAL_API_KEY:-}"
if [[ -z "$BASE" ]]; then
  echo "PUBLIC_API_URL not in $ENV_FILE — skip curl (set it for this check)."
else
  if [[ -n "$KEY" ]]; then
    HDR=(-H "X-Internal-Key: $KEY")
  else
    HDR=()
    echo "(no INTERNAL_API_KEY — /internal/slack/status may 401)"
  fi
  if curl -sS -f "${HDR[@]}" "${BASE%/}/internal/slack/status" 2>/dev/null | python3 -m json.tool 2>/dev/null || curl -sS "${HDR[@]}" "${BASE%/}/internal/slack/status"; then
    echo
  else
    echo "curl failed (wrong URL, TLS, or key)."
  fi
fi

echo
echo "=== 4) Recent worker logs (Slack / skip / error) ==="
"${DC[@]}" logs worker --tail 120 2>&1 | grep -iE 'slack|skipped|SlackApiError|chat.postMessage' || echo "(no matching lines in last 120)"

echo
echo "=== 5) Recent beat logs ==="
"${DC[@]}" logs beat --tail 60 2>&1 | grep -iE 'slack|Scheduler|beat' || echo "(no matching lines)"

echo
echo "=== Reminders ==="
echo "- Digest runs every 20 minutes UTC (not local time). See services/api/app/celery_app.py."
echo "- After editing deploy/.env: docker compose ... up -d worker beat"
echo "- Bot must be invited: /invite @YourBot in the channel; use channel ID (C…), not name."
echo "- Manual fire: curl -X POST \"\${PUBLIC_API_URL}/internal/slack/digest-now\" -H \"X-Internal-Key: ...\""
echo "  See docs/SLACK.md"
