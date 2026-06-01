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
if [ ! -f deploy/.env ]; then
  echo "FAIL: $(pwd)/deploy/.env not found" >&2
  exit 1
fi

BASE=$(grep -E '^PUBLIC_API_URL=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
if [ -z "$BASE" ]; then
  H=$(grep -E '^API_HOST=' deploy/.env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//')
  BASE="https://$H"
fi

KEY="${INTERNAL_KEY:-}"
# Prefer the Droplet's deploy/.env key (GitHub secret may be stale).
ENV_KEY="$(grep -E '^INTERNAL_API_KEY=' deploy/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//;s/"$//' || true)"
if [[ -n "${ENV_KEY}" ]]; then
  KEY="$ENV_KEY"
fi

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
  slack-inspect)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    export COMPOSE_REL
    # shellcheck source=scripts/remote/_compose_args.sh
    source "$ROOT/scripts/remote/_compose_args.sh"

    echo "=== SLACK_* in deploy/.env (values redacted) ==="
    grep -E '^SLACK_' deploy/.env 2>/dev/null | sed 's/=.*/=***/' || echo "(none)"

    echo "=== SLACK_* in repo-root .env (values redacted) ==="
    if [ -f .env ]; then
      grep -E '^SLACK_' .env 2>/dev/null | sed 's/=.*/=***/' || echo "(none)"
    else
      echo "(no .env at repo root)"
    fi

    # Common misconfig: token applied to repo-root .env but production reads deploy/.env.
    if grep -qE '^SLACK_BOT_TOKEN=xoxb-' .env 2>/dev/null && ! grep -qE '^SLACK_BOT_TOKEN=xoxb-' deploy/.env 2>/dev/null; then
      echo "=== Syncing SLACK_* from repo-root .env → deploy/.env ==="
      python3 <<'PY'
import pathlib
import re

root = pathlib.Path.cwd()
src = root / ".env"
dst = root / "deploy" / ".env"
text = dst.read_text(encoding="utf-8")
for key in ("SLACK_BOT_TOKEN", "SLACK_DIGEST_CHANNEL_ID", "SLACK_AGENT_DISCUSSION_CHANNEL_ID", "SLACK_AGENT_EVENT_UPDATES"):
    m = re.search(rf"^{re.escape(key)}=(.*)$", src.read_text(encoding="utf-8"), re.M)
    if not m:
        continue
    val = m.group(1).strip()
    if re.search(rf"^{re.escape(key)}=", text, re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={val}", text, count=1, flags=re.M)
    else:
        text = text.rstrip() + f"\n{key}={val}\n"
dst.write_text(text, encoding="utf-8")
print("Updated deploy/.env from repo-root .env")
PY
      echo "=== Restarting api, worker, beat with synced Slack env ==="
      docker compose "${ARGS[@]}" up -d --force-recreate api worker beat
    fi

    echo "=== docker compose ps api worker beat ==="
    docker compose "${ARGS[@]}" ps api worker beat

    echo "=== worker Slack config (from running container) ==="
    docker compose "${ARGS[@]}" exec -T worker python -c "
from app.config import get_settings
s = get_settings()
print('has_bot_token', bool((s.slack_bot_token or '').strip()))
print('has_digest_channel', bool((s.slack_digest_channel_id or '').strip()))
print('agent_event_updates', bool(getattr(s, 'slack_agent_event_updates', None)))
"

    echo "=== GET /internal/slack/status (via api exec) ==="
    POST_DEPLOY_PATH="/internal/slack/status" POST_DEPLOY_KEY="$KEY" \
      docker compose "${ARGS[@]}" exec -T -e POST_DEPLOY_PATH -e POST_DEPLOY_KEY api python -c "
import json, os, urllib.request
key = (os.environ.get('POST_DEPLOY_KEY') or '').strip()
req = urllib.request.Request('http://127.0.0.1:8000' + os.environ['POST_DEPLOY_PATH'])
if key:
    req.add_header('X-Internal-Key', key)
print(urllib.request.urlopen(req, timeout=30).read().decode())
"

    echo "=== GET /internal/slack/last-digest ==="
    POST_DEPLOY_PATH="/internal/slack/last-digest" POST_DEPLOY_KEY="$KEY" \
      docker compose "${ARGS[@]}" exec -T -e POST_DEPLOY_PATH -e POST_DEPLOY_KEY api python -c "
import json, os, urllib.request
key = (os.environ.get('POST_DEPLOY_KEY') or '').strip()
req = urllib.request.Request('http://127.0.0.1:8000' + os.environ['POST_DEPLOY_PATH'])
if key:
    req.add_header('X-Internal-Key', key)
print(urllib.request.urlopen(req, timeout=30).read().decode())
"

    echo "=== POST /internal/slack/digest-now (enqueue standup) ==="
    POST_DEPLOY_PATH="/internal/slack/digest-now" POST_DEPLOY_KEY="$KEY" \
      docker compose "${ARGS[@]}" exec -T -e POST_DEPLOY_PATH -e POST_DEPLOY_KEY api python -c "
import os, urllib.request
key = (os.environ.get('POST_DEPLOY_KEY') or '').strip()
req = urllib.request.Request(
    'http://127.0.0.1:8000' + os.environ['POST_DEPLOY_PATH'],
    data=b'{}',
    method='POST',
    headers={'Content-Type': 'application/json'},
)
if key:
    req.add_header('X-Internal-Key', key)
print(urllib.request.urlopen(req, timeout=120).read().decode())
"

    echo "=== worker logs (slack, tail 40) ==="
    docker compose "${ARGS[@]}" logs --no-color --tail 40 worker 2>/dev/null | grep -iE 'slack|SKIPPED' || echo "(no recent slack lines)"
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
