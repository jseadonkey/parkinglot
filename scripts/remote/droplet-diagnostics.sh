#!/usr/bin/env bash
# Run on the Droplet from repo root (after deploy sync).
# Usage: bash scripts/remote/droplet-diagnostics.sh [compose_file] [log_tail] [curl_ready]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

COMPOSE_REL="${1:-deploy/docker-compose.production.yml}"
LOG_TAIL="${2:-50}"
CURL_READY="${3:-true}"

if [ ! -f deploy/.env ]; then
  echo "Missing deploy/.env — create from deploy/env.production.example first." >&2
  exit 1
fi

# shellcheck source=scripts/remote/_compose_args.sh
source "$ROOT/scripts/remote/_compose_args.sh"

echo "=== docker compose ps ==="
docker compose "${ARGS[@]}" ps -a
echo ""
echo "=== beat / worker ps ==="
docker compose "${ARGS[@]}" ps beat worker
echo ""
echo "=== beat logs (tail 30) ==="
docker compose "${ARGS[@]}" logs --no-color --tail 30 beat || true
echo ""
echo "=== worker logs (tail 80, slack) ==="
docker compose "${ARGS[@]}" logs --no-color --tail 80 worker 2>/dev/null | grep -iE 'slack_agent_digest|slack not configured|SKIPPED' || \
  docker compose "${ARGS[@]}" logs --no-color --tail 40 worker || true
echo ""
echo "=== api logs (tail) ==="
docker compose "${ARGS[@]}" logs --no-color --tail "$LOG_TAIL" api || true
echo ""

if [ "$CURL_READY" = "true" ]; then
  BASE=$(grep -E '^PUBLIC_API_URL=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
  if [ -z "$BASE" ]; then
    H=$(grep -E '^API_HOST=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
    BASE="https://$H"
  fi
  echo "=== curl $BASE/ready ==="
  curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/ready"
  echo ""
  echo "=== GET $BASE/internal/slack/status ==="
  KEY=$(grep -E '^INTERNAL_API_KEY=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
  if [ -n "$KEY" ]; then
    curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status" -H "X-Internal-Key: $KEY"
  else
    curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status"
  fi
  echo ""
else
  echo "Skipping /ready curl (curl_ready=$CURL_READY)."
fi
