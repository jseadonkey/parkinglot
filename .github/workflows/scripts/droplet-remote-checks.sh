#!/usr/bin/env bash
# Sourced by GitHub Actions over SSH (lives in repo; rsynced on deploy).
# Usage on Droplet: bash .github/workflows/scripts/droplet-remote-checks.sh <mode> [args...]
set -euo pipefail

MODE="${1:-}"
shift || true

# When streamed over SSH (bash -s), BASH_SOURCE is unset; use cwd after `cd $REMOTE_PATH`.
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "-" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  cd "$ROOT"
else
  ROOT="$(pwd)"
fi
test -f deploy/.env

BASE=$(grep -E '^PUBLIC_API_URL=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
if [ -z "$BASE" ]; then
  H=$(grep -E '^API_HOST=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
  BASE="https://$H"
fi

KEY="${INTERNAL_KEY:-}"
KEY="${KEY:-$(grep -E '^INTERNAL_API_KEY=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')}"

case "$MODE" in
  endpoints)
    CURL_HEALTH="${1:-true}"
    CURL_READY="${2:-true}"
    CHECK_SLACK="${3:-true}"
    if [ "$CURL_HEALTH" = "true" ]; then
      echo "=== GET $BASE/health ==="
      curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/health"
      echo ""
    fi
    if [ "$CURL_READY" = "true" ]; then
      echo "=== GET $BASE/ready ==="
      curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/ready"
      echo ""
    fi
    if [ "$CHECK_SLACK" = "true" ]; then
      echo "=== GET $BASE/internal/slack/status ==="
      if [ -n "$KEY" ]; then
        curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status" -H "X-Internal-Key: $KEY"
      else
        curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status"
      fi
      echo ""
    fi
    ;;
  last-digest)
    if [ -n "$KEY" ]; then
      curl -fsSk --connect-timeout 15 --max-time 60 "$BASE/internal/slack/last-digest" -H "X-Internal-Key: $KEY"
    else
      curl -fsSk --connect-timeout 15 --max-time 60 "$BASE/internal/slack/last-digest"
    fi
    ;;
  digest-now)
    echo "POST $BASE/internal/slack/digest-now"
    if [ -n "$KEY" ]; then
      curl -fsSk --connect-timeout 15 --max-time 60 -X POST "$BASE/internal/slack/digest-now" \
        -H "Content-Type: application/json" -H "X-Internal-Key: $KEY" -d '{}'
    else
      curl -fsSk --connect-timeout 15 --max-time 60 -X POST "$BASE/internal/slack/digest-now" \
        -H "Content-Type: application/json" -d '{}'
    fi
    echo ""
    ;;
  diagnostics)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    LOG_TAIL="${2:-50}"
    CURL_READY="${3:-true}"
    export COMPOSE_REL
    # shellcheck source=scripts/remote/_compose_args.sh
    source "$ROOT/scripts/remote/_compose_args.sh"
    echo "=== docker compose ps (api worker beat) ==="
    docker compose "${ARGS[@]}" ps api worker beat
    echo ""
    echo "=== worker logs (slack) ==="
    docker compose "${ARGS[@]}" logs --no-color --tail 80 worker 2>/dev/null | grep -iE 'slack_agent_digest|SKIPPED|Slack' || \
      docker compose "${ARGS[@]}" logs --no-color --tail 40 worker || true
    echo ""
    if [ "$CURL_READY" = "true" ]; then
      echo "=== GET $BASE/ready ==="
      curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/ready"
      echo ""
      echo "=== GET $BASE/internal/slack/status ==="
      if [ -n "$KEY" ]; then
        curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status" -H "X-Internal-Key: $KEY"
      else
        curl -fsSk --connect-timeout 15 --max-time 30 "$BASE/internal/slack/status"
      fi
      echo ""
    fi
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    exit 2
    ;;
esac
