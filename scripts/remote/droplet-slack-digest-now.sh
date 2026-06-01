#!/usr/bin/env bash
# POST /internal/slack/digest-now from the Droplet (enqueue Celery digest task).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
test -f deploy/.env

BASE=$(grep -E '^PUBLIC_API_URL=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
if [ -z "$BASE" ]; then
  H=$(grep -E '^API_HOST=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
  BASE="https://$H"
fi

KEY="${1:-}"
KEY="${KEY:-$(grep -E '^INTERNAL_API_KEY=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')}"

echo "POST $BASE/internal/slack/digest-now"
if [ -n "$KEY" ]; then
  curl -fsSk --connect-timeout 15 --max-time 60 -X POST "$BASE/internal/slack/digest-now" \
    -H "Content-Type: application/json" \
    -H "X-Internal-Key: $KEY" \
    -d '{}'
else
  curl -fsSk --connect-timeout 15 --max-time 60 -X POST "$BASE/internal/slack/digest-now" \
    -H "Content-Type: application/json" \
    -d '{}'
fi
echo
