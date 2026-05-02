#!/usr/bin/env bash
# Run on the Droplet from the repo root after `docker compose up` (API + worker must be up).
# Enqueues Celery Slack jobs via the public API URL from deploy/.env.
#
# Usage:
#   ./scripts/post-deploy-slack.sh all    # POST /internal/slack/full-update-now (digest + qualified + dual-agent)
#   ./scripts/post-deploy-slack.sh full  # same as all
#   ./scripts/post-deploy-slack.sh digest
#   ./scripts/post-deploy-slack.sh qualified
#   ./scripts/post-deploy-slack.sh discussion
#   ./scripts/post-deploy-slack.sh none
#
# Env:
#   DEPLOY_ENV_FILE — override path to env file (default: ./deploy/.env)
#
# Reads from deploy/.env:
#   PUBLIC_API_URL (or API_HOST fallback), INTERNAL_API_KEY (optional X-Internal-Key)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/deploy/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

_env_val() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//'
}

BASE="$(_env_val PUBLIC_API_URL)"
if [[ -z "${BASE}" ]]; then
  H="$(_env_val API_HOST)"
  if [[ -n "$H" ]]; then
    BASE="https://$H"
  fi
fi
if [[ -z "${BASE}" ]]; then
  echo "Set PUBLIC_API_URL or API_HOST in $ENV_FILE" >&2
  exit 1
fi

KEY="$(_env_val INTERNAL_API_KEY)"
MODE="${1:-none}"

if [[ "$MODE" != "none" ]]; then
  echo "Waiting briefly for API/worker to accept connections…"
  sleep 3
fi

curl_post() {
  local path="$1"
  local url="${BASE%/}${path}"
  echo "POST $url"
  if [[ -n "${KEY}" ]]; then
    curl -fsSk --connect-timeout 15 --max-time 120 -X POST "$url" \
      -H "Content-Type: application/json" \
      -H "X-Internal-Key: $KEY" \
      -d '{}'
  else
    curl -fsSk --connect-timeout 15 --max-time 120 -X POST "$url" \
      -H "Content-Type: application/json" \
      -d '{}'
  fi
  echo
}

case "$MODE" in
  none)
    echo "post-deploy-slack: mode=none, nothing to do"
    ;;
  digest)
    curl_post "/internal/slack/digest-now"
    ;;
  qualified)
    curl_post "/internal/slack/qualified-parcels-now"
    ;;
  discussion)
    curl_post "/internal/slack/agent-discussion-now"
    ;;
  all|full)
    curl_post "/internal/slack/full-update-now"
    ;;
  *)
    echo "Usage: $0 {all|full|digest|qualified|discussion|none}" >&2
    exit 2
    ;;
esac
