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
#   LOCAL_API_FALLBACK — optional host curl fallback if PUBLIC_API_URL fails (DNS/refused)
#   Final fallback: docker compose exec api → http://127.0.0.1:8000 (see deploy/docker-compose.production.yml)
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
# If PUBLIC_API_URL uses a hostname that does not resolve on the Droplet itself, curl exits 6.
# Set LOCAL_API_FALLBACK in deploy/.env (e.g. http://127.0.0.1:18000 per docs/PROJECT-FACTS.md).
LOCAL_FB="$(_env_val LOCAL_API_FALLBACK)"
LOCAL_FB="${LOCAL_FB:-http://127.0.0.1:18000}"
MODE="${1:-none}"

# POST from inside the api container (no host port / DNS required).
_compose_api_post() {
  local path="$1"
  cd "$ROOT"
  local args=( -f deploy/docker-compose.production.yml --env-file deploy/.env )
  if [[ -f deploy/docker-compose.postgis-addon.yml ]]; then
    args+=( -f deploy/docker-compose.postgis-addon.yml )
  fi
  echo "POST http://127.0.0.1:8000${path} (via docker compose exec api)" >&2
  POST_DEPLOY_PATH="$path" POST_DEPLOY_KEY="$KEY" docker compose "${args[@]}" exec -T \
    -e POST_DEPLOY_PATH -e POST_DEPLOY_KEY \
    api python -c "
import os, urllib.request
path = os.environ['POST_DEPLOY_PATH']
key = (os.environ.get('POST_DEPLOY_KEY') or '').strip()
url = 'http://127.0.0.1:8000' + path
req = urllib.request.Request(url, data=b'{}', method='POST', headers={'Content-Type': 'application/json'})
if key:
    req.add_header('X-Internal-Key', key)
resp = urllib.request.urlopen(req, timeout=120)
print(resp.read().decode())
"
}

if [[ "$MODE" != "none" ]]; then
  echo "Waiting briefly for API/worker to accept connections…"
  sleep 3
fi

_do_post() {
  local url="$1"
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
}

curl_post() {
  local path="$1"
  local url="${BASE%/}${path}"
  local ec=0
  echo "POST $url"
  set +e
  _do_post "$url"
  ec=$?
  set -e
  if [[ "$ec" -eq 6 || "$ec" -eq 7 ]] && [[ -n "${LOCAL_FB}" ]]; then
    echo "curl public URL failed (exit $ec); retrying LOCAL_API_FALLBACK=${LOCAL_FB}" >&2
    url="${LOCAL_FB%/}${path}"
    echo "POST $url"
    set +e
    _do_post "$url"
    ec=$?
    set -e
  fi
  if [[ "$ec" -ne 0 ]]; then
    echo "curl still failing (exit $ec); trying docker compose exec api on :8000 …" >&2
    set +e
    _compose_api_post "$path"
    local dc_ec=$?
    set -e
    if [[ "$dc_ec" -ne 0 ]]; then
      echo "docker compose fallback failed (exit $dc_ec)" >&2
      return "$dc_ec"
    fi
  fi
  echo
  return 0
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
