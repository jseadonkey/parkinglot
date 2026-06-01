#!/usr/bin/env bash
# Curl /health, /ready, optional /internal/slack/status from the Droplet.
# Usage: bash scripts/remote/droplet-endpoint-checks.sh [curl_health] [curl_ready] [check_slack]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
test -f deploy/.env

CURL_HEALTH="${1:-true}"
CURL_READY="${2:-true}"
CHECK_SLACK="${3:-true}"

BASE=$(grep -E '^PUBLIC_API_URL=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
if [ -z "$BASE" ]; then
  H=$(grep -E '^API_HOST=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
  BASE="https://$H"
fi

KEY=$(grep -E '^INTERNAL_API_KEY=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')

if [ "$CURL_HEALTH" = "true" ]; then
  echo "=== GET $BASE/health ==="
  curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/health"
  echo ""
else
  echo "Skipping /health"
fi

if [ "$CURL_READY" = "true" ]; then
  echo "=== GET $BASE/ready ==="
  curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/ready"
  echo ""
else
  echo "Skipping /ready"
fi

if [ "$CHECK_SLACK" = "true" ]; then
  echo "=== GET $BASE/internal/slack/status ==="
  if [ -n "$KEY" ]; then
    curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status" -H "X-Internal-Key: $KEY"
  else
    curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status"
  fi
  echo ""
else
  echo "Skipping slack status"
fi
