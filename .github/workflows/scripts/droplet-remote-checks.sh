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

# Curl an internal API path; fall back to in-container localhost when PUBLIC_API_URL is unreachable.
_internal_api_get() {
  local path="$1"
  local body=""
  if [ -n "$KEY" ]; then
    body="$(curl -sSk --connect-timeout 10 --max-time 45 "${BASE}${path}" -H "X-Internal-Key: $KEY" 2>/dev/null || true)"
  else
    body="$(curl -sSk --connect-timeout 10 --max-time 45 "${BASE}${path}" 2>/dev/null || true)"
  fi
  if [ -n "$body" ]; then
    printf '%s' "$body"
    return 0
  fi
  local compose_rel
  compose_rel="${COMPOSE_REL:-deploy/docker-compose.production.ghcr.yml}"
  if ! docker compose -f "$compose_rel" --env-file deploy/.env ps -q api 2>/dev/null | grep -q .; then
    return 0
  fi
  docker compose -f "$compose_rel" --env-file deploy/.env exec -T -e "API_PATH=$path" api python - <<'PY'
import os
import urllib.error
import urllib.request

path = os.environ["API_PATH"]
headers = {"Accept": "application/json"}
key = (os.environ.get("INTERNAL_API_KEY") or "").strip()
if key:
    headers["X-Internal-Key"] = key
req = urllib.request.Request(f"http://127.0.0.1:8000{path}", headers=headers)
try:
    with urllib.request.urlopen(req, timeout=45) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.read().decode() if exc.fp else str(exc))
PY
}

_internal_api_post_via_container() {
  local path="$1"
  local payload="${2:-"{}"}"
  local compose_rel="${COMPOSE_REL:-deploy/docker-compose.production.ghcr.yml}"
  if ! docker compose -f "$compose_rel" --env-file deploy/.env ps -q api 2>/dev/null | grep -q .; then
    echo "api container not running"
    return 1
  fi
  docker compose -f "$compose_rel" --env-file deploy/.env exec -T \
    -e "API_PATH=$path" -e "API_PAYLOAD=$payload" -e "INTERNAL_API_KEY=$KEY" api python - <<'PY'
import os
import urllib.error
import urllib.request

path = os.environ["API_PATH"]
payload = (os.environ.get("API_PAYLOAD") or "{}").encode("utf-8")
headers = {"Accept": "application/json", "Content-Type": "application/json"}
key = (os.environ.get("INTERNAL_API_KEY") or "").strip()
if key:
    headers["X-Internal-Key"] = key
req = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=payload, method="POST", headers=headers)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.read().decode() if exc.fp else str(exc))
PY
}

_internal_api_post() {
  local path="$1"
  local payload="${2:-"{}"}"
  # Non-empty JSON bodies: POST via API container (curl through Caddy often drops or corrupts body).
  if [ "$payload" != "{}" ]; then
    _internal_api_post_via_container "$path" "$payload"
    return $?
  fi
  local body=""
  local http_code="000"
  if [ -n "$KEY" ]; then
    body="$(curl -sSk --connect-timeout 15 --max-time 60 -w $'\n%{http_code}' -X POST "${BASE}${path}" \
      -H "Content-Type: application/json" -H "X-Internal-Key: $KEY" -d "$payload" 2>/dev/null || true)"
  else
    body="$(curl -sSk --connect-timeout 15 --max-time 60 -w $'\n%{http_code}' -X POST "${BASE}${path}" \
      -H "Content-Type: application/json" -d "$payload" 2>/dev/null || true)"
  fi
  if [ -n "$body" ]; then
    http_code="$(printf '%s' "$body" | tail -n 1)"
    body="$(printf '%s' "$body" | sed '$d')"
  fi
  case "$http_code" in
    200|201|202|204)
      printf '%s' "$body"
      return 0
      ;;
  esac
  _internal_api_post_via_container "$path" "$payload"
}

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
    set +e
    body="$(_internal_api_get "/internal/slack/last-digest")"
    set -e
    if [ -z "$body" ]; then
      echo '{"found":false,"error":"unreachable"}'
    else
      printf '%s\n' "$body"
    fi
    ;;
  digest-now)
    echo "POST $BASE/internal/slack/digest-now"
    _internal_api_post "/internal/slack/digest-now"
    echo ""
    ;;
  post-slack-text)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    export COMPOSE_REL
    TEXT="${NOTIFY_TEXT:-}"
    if [ -z "$TEXT" ] && [ ! -t 0 ]; then
      TEXT="$(cat)"
    fi
    if [ -z "$TEXT" ]; then
      echo "FAIL: post-slack-text needs NOTIFY_TEXT or stdin" >&2
      exit 1
    fi
    export NOTIFY_TEXT="$TEXT"
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env exec -T -e NOTIFY_TEXT -e "NOTIFY_CHANNEL=${NOTIFY_CHANNEL:-}" api python - <<'PY'
import os
from app.config import get_settings
from app.slack_digest import post_text_to_slack

settings = get_settings()
text = os.environ["NOTIFY_TEXT"]
channel = (os.environ.get("NOTIFY_CHANNEL") or "").strip() or None
posted = post_text_to_slack(settings, text=text[:3900], channel_id=channel)
print("slack_posted", posted)
PY
    ;;
  sync-slack-channels)
    echo "=== align alert channel IDs with SLACK_DIGEST_CHANNEL_ID ==="
    python3 - <<'PY'
import pathlib

path = pathlib.Path("deploy/.env")
text = path.read_text(encoding="utf-8")
values = {}
for line in text.splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    values[k.strip()] = v.strip().strip('"')

digest = values.get("SLACK_DIGEST_CHANNEL_ID", "") or "C0B0VPSAH44"
updates = {
    "SITE_WATCHDOG_SLACK_CHANNEL_ID": digest,
    "SLACK_AGENT_DISCUSSION_CHANNEL_ID": values.get("SLACK_AGENT_DISCUSSION_CHANNEL_ID", "") or digest,
}
out: list[str] = []
seen = set()
for line in text.splitlines():
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, val in updates.items():
    if key not in seen:
        out.append(f"{key}={val}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print(f"digest_channel={digest}")
for k, v in updates.items():
    print(f"{k}={v}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps api worker worker-slack beat
    ;;
  slack-inspect)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    export COMPOSE_REL
    # GHCR stack — avoid postgis addon auto-detection (Managed Postgres on production).
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    set +e

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
      echo "=== Restarting api, worker, worker-slack, beat with synced Slack env ==="
      docker compose "${ARGS[@]}" up -d --force-recreate api worker worker-slack beat
    fi

    echo "=== docker compose ps api worker worker-slack beat ==="
    docker compose "${ARGS[@]}" ps api worker worker-slack beat

    echo "=== worker-slack Slack config (from running container) ==="
    docker compose "${ARGS[@]}" exec -T worker-slack python -c "
from app.config import get_settings
s = get_settings()
print('has_bot_token', bool((s.slack_bot_token or '').strip()))
print('has_digest_channel', bool((s.slack_digest_channel_id or '').strip()))
"

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

    echo "=== waiting 30s for standup digest task ==="
    sleep 30

    echo "=== GET /internal/slack/last-digest (after enqueue) ==="
    LAST_DIGEST="$(POST_DEPLOY_PATH="/internal/slack/last-digest" POST_DEPLOY_KEY="$KEY" \
      docker compose "${ARGS[@]}" exec -T -e POST_DEPLOY_PATH -e POST_DEPLOY_KEY api python -c "
import os, urllib.request
key = (os.environ.get('POST_DEPLOY_KEY') or '').strip()
req = urllib.request.Request('http://127.0.0.1:8000' + os.environ['POST_DEPLOY_PATH'])
if key:
    req.add_header('X-Internal-Key', key)
print(urllib.request.urlopen(req, timeout=30).read().decode())
" 2>&1 || echo '{"found":false}')"
    echo "$LAST_DIGEST"

    if ! echo "$LAST_DIGEST" | grep -qE '"found"[[:space:]]*:[[:space:]]*true'; then
      echo "=== Celery queue slow — posting standup digest directly from worker ==="
      docker compose "${ARGS[@]}" exec -T worker python -c "
from app.audit import write_audit
from app.config import get_settings
from app.db.session import SessionLocal
from app.slack_digest import build_slack_digest_blocks, post_digest_to_slack

s = get_settings()
ch = (s.slack_digest_channel_id or '').strip()
db = SessionLocal()
try:
    blocks, fallback = build_slack_digest_blocks(db, hours=4)
finally:
    db.close()
posted = post_digest_to_slack(s, blocks, fallback)
audit_db = SessionLocal()
try:
    write_audit(
        audit_db,
        actor='celery:slack_agent_digest',
        action='slack_digest_posted',
        entity_type='slack_channel',
        entity_id=ch,
        meta={
            'slack_ts': posted.get('ts'),
            'channel': posted.get('channel'),
            'fallback_preview': (fallback or '')[:240],
        },
    )
finally:
    audit_db.close()
print('standup_posted', posted)
" 2>&1
    fi

    echo "=== beat logs (scheduler, tail 30) ==="
    docker compose "${ARGS[@]}" logs --no-color --tail 30 beat 2>/dev/null || true

    echo "=== worker logs (slack, tail 40) ==="
    docker compose "${ARGS[@]}" logs --no-color --tail 80 worker 2>/dev/null | grep -iE 'slack_agent_digest|slack_digest_posted|SKIPPED' || true

    echo "=== api ps ==="
    docker compose "${ARGS[@]}" ps api 2>/dev/null || true
    set -e
    ;;
  diagnostics)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    LOG_TAIL="${2:-50}"
    CURL_READY="${3:-true}"
    export COMPOSE_REL
    # shellcheck source=scripts/remote/_compose_args.sh
    source "$ROOT/scripts/remote/_compose_args.sh"
    echo "=== docker compose ps (api worker worker-slack beat operator-console) ==="
    docker compose "${ARGS[@]}" ps api worker worker-slack beat operator-console approval-ui
    echo ""
    echo "=== operator-console → api GET /approvals (first 120 chars) ==="
    docker compose "${ARGS[@]}" exec -T operator-console wget -qO- --timeout=15 \
      "http://api:8000/approvals?status=pending&limit=3" 2>&1 | head -c 120 || echo "wget failed"
    echo ""
    echo ""
    echo "=== operator-console env API_SERVER_URL ==="
    docker compose "${ARGS[@]}" exec -T operator-console printenv API_SERVER_URL 2>/dev/null || true
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
  resources)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    export COMPOSE_REL
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    echo "=== hostname / uptime ==="
    hostname
    uptime
    echo ""
    echo "=== CPU ==="
    nproc
    grep -m1 "model name" /proc/cpuinfo || true
    echo ""
    echo "=== memory (free -h) ==="
    free -h
    echo ""
    echo "=== disk (df -h) ==="
    df -h / /var/lib/docker 2>/dev/null || df -h /
    echo ""
    echo "=== block devices (lsblk) ==="
    lsblk -o NAME,SIZE,FSUSE%,MOUNTPOINT 2>/dev/null || true
    echo ""
    echo "=== docker stats (no stream) ==="
    docker stats --no-stream "${ARGS[@]}" 2>/dev/null || docker stats --no-stream 2>/dev/null || true
    echo ""
    echo "=== compose ps ==="
    docker compose "${ARGS[@]}" ps 2>/dev/null || true
    ;;
  disk-grow)
    echo "=== lsblk before ==="
    lsblk -o NAME,SIZE,FSUSE%,MOUNTPOINT
    ROOT_PART="$(findmnt -n -o SOURCE /)"
    echo "root partition: $ROOT_PART"
    if command -v growpart >/dev/null 2>&1; then
      DISK="/dev/vda"
      PART_NUM="1"
      growpart "$DISK" "$PART_NUM" || true
    else
      echo "growpart not installed; run: apt-get update && apt-get install -y cloud-guest-utils"
    fi
    if [[ "$ROOT_PART" == *"vda"* ]]; then
      resize2fs "$ROOT_PART" || true
    fi
    echo ""
    echo "=== df -h after ==="
    df -h /
    lsblk -o NAME,SIZE,FSUSE%,MOUNTPOINT
    ;;
  relieve-load)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    # Fall back to whatever stack is actually running (manual deploy uses deploy-* project).
    if ! docker compose -f "$COMPOSE_REL" --env-file deploy/.env ps -q worker 2>/dev/null | grep -q .; then
      for alt in deploy/docker-compose.production.yml deploy/docker-compose.production.ghcr-full.yml; do
        if docker compose -f "$alt" --env-file deploy/.env ps -q worker 2>/dev/null | grep -q .; then
          COMPOSE_REL="$alt"
          break
        fi
      done
    fi
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    echo "=== using compose file: $COMPOSE_REL ==="
    echo "=== load / memory ==="
    uptime
    free -h
    echo ""
    echo "=== redis queue lengths (before) ==="
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || echo "parking: (n/a)"
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || echo "slack: (n/a)"
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN celery 2>/dev/null || echo "celery: (n/a)"
    echo ""
    echo "=== disable SCHEDULED_ENQUEUE_UNSCORED in deploy/.env ==="
    python3 <<'PY'
import pathlib
import re

path = pathlib.Path("deploy/.env")
text = path.read_text(encoding="utf-8")
key = "SCHEDULED_ENQUEUE_UNSCORED_ENABLED"
if re.search(rf"^{re.escape(key)}=", text, re.M):
    text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}=false", text, count=1, flags=re.M)
else:
    text = text.rstrip() + f"\n{key}=false\n"
path.write_text(text, encoding="utf-8")
print(f"Set {key}=false")
PY
    echo ""
    echo "=== purge parking Celery queue (keeps slack queue) ==="
    docker compose "${ARGS[@]}" exec -T worker celery -A app.celery_app purge -f -Q parking 2>&1 || true
    echo ""
    echo "=== restart beat + workers ==="
    docker compose "${ARGS[@]}" up -d --force-recreate beat worker worker-slack
    echo ""
    echo "=== redis queue lengths (after) ==="
    sleep 3
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || true
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || true
    echo ""
    docker stats --no-stream "${ARGS[@]}" 2>/dev/null | head -12 || docker stats --no-stream | head -12
    echo ""
    echo "Done. Re-enable enqueue with SCHEDULED_ENQUEUE_UNSCORED_ENABLED=true and recreate beat when ready."
    ;;
  enable-enqueue)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    ENQUEUE_LIMIT="${ENQUEUE_LIMIT:-50}"
    if ! docker compose -f "$COMPOSE_REL" --env-file deploy/.env ps -q worker 2>/dev/null | grep -q .; then
      for alt in deploy/docker-compose.production.yml deploy/docker-compose.production.ghcr-full.yml; do
        if docker compose -f "$alt" --env-file deploy/.env ps -q worker 2>/dev/null | grep -q .; then
          COMPOSE_REL="$alt"
          break
        fi
      done
    fi
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    echo "=== using compose file: $COMPOSE_REL ==="
    echo "=== load / memory ==="
    uptime
    free -h
    echo ""
    echo "=== redis queue lengths (before) ==="
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || echo "parking: (n/a)"
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || echo "slack: (n/a)"
    echo ""
    echo "=== enable SCHEDULED_ENQUEUE_UNSCORED in deploy/.env (limit=${ENQUEUE_LIMIT}) ==="
    ENQUEUE_LIMIT="$ENQUEUE_LIMIT" python3 <<'PY'
import os
import pathlib
import re

path = pathlib.Path("deploy/.env")
text = path.read_text(encoding="utf-8")
limit = os.environ["ENQUEUE_LIMIT"]

def set_key(key: str, value: str) -> None:
    global text
    if re.search(rf"^{re.escape(key)}=", text, re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, count=1, flags=re.M)
    else:
        text = text.rstrip() + f"\n{key}={value}\n"

set_key("SCHEDULED_ENQUEUE_UNSCORED_ENABLED", "true")
set_key("SCHEDULED_ENQUEUE_UNSCORED_LIMIT", limit)
path.write_text(text, encoding="utf-8")
print("Set SCHEDULED_ENQUEUE_UNSCORED_ENABLED=true")
print(f"Set SCHEDULED_ENQUEUE_UNSCORED_LIMIT={limit}")
PY
    echo ""
    echo "=== restart beat + workers ==="
    docker compose "${ARGS[@]}" up -d --force-recreate beat worker worker-slack
    echo ""
    echo "=== redis queue lengths (after) ==="
    sleep 3
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || true
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || true
    echo ""
    docker stats --no-stream "${ARGS[@]}" 2>/dev/null | head -12 || docker stats --no-stream | head -12
    echo ""
    echo "Done. Scheduled incomplete-pipeline enqueue is ON (limit=${ENQUEUE_LIMIT} per run)."
    ;;
  pipeline-velocity)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    export COMPOSE_REL
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    echo "=== scheduled enqueue config (deploy/.env) ==="
    grep -E '^SCHEDULED_ENQUEUE_' deploy/.env 2>/dev/null || echo "(no SCHEDULED_ENQUEUE_* lines)"
    echo ""
    echo "=== load / memory ==="
    uptime
    free -h | head -2
    echo ""
    echo "=== redis queue lengths ==="
    PARKING_Q="$(docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || echo n/a)"
    SLACK_Q="$(docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || echo n/a)"
    echo "parking: ${PARKING_Q}"
    echo "slack: ${SLACK_Q}"
    echo ""
    echo "=== export-readiness (backlog gaps) ==="
    if [ -n "$KEY" ]; then
      _internal_api_get "/internal/stats/export-readiness" || echo "export-readiness failed"
    else
      echo "INTERNAL_API_KEY not set — skipping export-readiness"
    fi
    echo ""
    echo "=== scoring-summary (funnel counts) ==="
    if [ -n "$KEY" ]; then
      _internal_api_get "/internal/stats/scoring-summary" || echo "scoring-summary failed"
    else
      echo "INTERNAL_API_KEY not set — skipping scoring-summary"
    fi
    echo ""
    echo "=== worker parking (active/reserved) ==="
    docker compose "${ARGS[@]}" exec -T worker celery -A app.celery_app inspect active -d parking@ 2>/dev/null | head -40 || true
    echo ""
    echo "=== beat schedule snippet (enqueue-unscored) ==="
    docker compose "${ARGS[@]}" logs --no-color --tail 200 beat 2>/dev/null | grep -iE 'enqueue unscored|enqueue-unscored|Beat:' | tail -8 || true
    echo ""
    echo "=== worker parking recent run_pipeline (tail) ==="
    docker compose "${ARGS[@]}" logs --no-color --tail 120 worker 2>/dev/null | grep -iE 'run_pipeline|succeeded|failed' | tail -15 || true
    ;;
  outreach-drafts)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    PID="e3308aee-f7ef-4a89-8731-54932aec07f5"
    echo "=== outreach schema + drafts probe (parcel $PID) ==="
    docker compose "${ARGS[@]}" exec -T api python - <<'PY'
import traceback
import uuid

from app.db.schema_compat import table_exists
from app.db.session import SessionLocal

db = SessionLocal()
for name in ("parcel_contact_points", "outreach_templates", "outreach_attempts"):
    print(name, table_exists(db, name))
try:
    from app.db.models import Parcel
    from app.outreach_contacts import load_persisted_contact_points, merge_brief_with_persisted_contacts
    from app.outreach_templates import build_parcel_outreach_drafts
    from parking_core.models import OwnerOutreachBrief

    pid = uuid.UUID("e3308aee-f7ef-4a89-8731-54932aec07f5")
    parcel = db.get(Parcel, pid)
    brief = OwnerOutreachBrief.model_validate(parcel.owner_outreach_brief)
    persisted = load_persisted_contact_points(db, pid)
    merged = merge_brief_with_persisted_contacts(brief, persisted)
    drafts = build_parcel_outreach_drafts(db, parcel=parcel, brief=merged)
    print("drafts_ok", len(drafts))
except Exception:
    traceback.print_exc()
PY
    echo ""
    echo "=== GET $BASE/parcels/$PID/outreach/drafts ==="
    curl -sS -w "\nHTTP %{http_code}\n" "$BASE/parcels/$PID/outreach/drafts" || true
    ;;
  site-watchdog-server)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    export COMPOSE_REL
    echo "=== site watchdog server checks (JSON on last line) ==="
    docker compose "${ARGS[@]}" exec -T -e COMPOSE_REL api python - <<'PY'
import json
import os
import subprocess

from app.config import get_settings
from app.db.session import SessionLocal
from app.site_watchdog import WatchdogCheck, build_report, run_server_checks

checks: list[WatchdogCheck] = []
db = SessionLocal()
try:
    checks.extend(run_server_checks(db, get_settings(), source="github-ssh"))
finally:
    db.close()

try:
    line = subprocess.check_output(["df", "-h", "/"], text=True).strip().splitlines()[-1]
    parts = line.split()
    use_pct = int(parts[4].rstrip("%")) if len(parts) >= 5 else 0
    checks.append(WatchdogCheck("disk_root", use_pct < 90, line, source="github-ssh"))
except Exception as exc:
    checks.append(WatchdogCheck("disk_root", False, str(exc)[:200], source="github-ssh"))

unhealthy: list[str] = []
try:
    rel = os.environ.get("COMPOSE_REL", "deploy/docker-compose.production.ghcr.yml")
    out = subprocess.check_output(
        ["docker", "compose", "-f", rel, "--env-file", "deploy/.env", "ps", "--format", "{{.Name}}:{{.Health}}"],
        text=True,
        cwd="/opt/workspaces/parkinglot" if os.path.isdir("/opt/workspaces/parkinglot") else os.getcwd(),
    )
    for row in out.splitlines():
        h = row.split(":")[-1].lower() if ":" in row else ""
        if h and h not in ("healthy", ""):
            unhealthy.append(row.strip())
    checks.append(
        WatchdogCheck(
            "compose_health",
            len(unhealthy) == 0,
            "ok" if not unhealthy else "; ".join(unhealthy[:8]),
            source="github-ssh",
        )
    )
except Exception as exc:
    checks.append(WatchdogCheck("compose_health", False, str(exc)[:200], source="github-ssh"))

report = build_report(checks, runner="github-ssh")
print("WATCHDOG_JSON=" + json.dumps(report))
PY
    ;;
  pause-wa-statewide-rollout)
    echo "=== pause WA statewide rollout (prioritize top parcels) ==="
    python3 - <<'PY'
import pathlib
path = pathlib.Path("deploy/.env")
lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
out = []
for line in lines:
    if line.startswith("WA_STATEWIDE_ROLLOUT_ENABLED="):
        out.append("WA_STATEWIDE_ROLLOUT_ENABLED=false")
    else:
        out.append(line)
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("Set WA_STATEWIDE_ROLLOUT_ENABLED=false")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps worker beat
    ;;
  enable-priority-pipeline)
    echo "=== enable priority pipeline enqueue (top entitlement first) ==="
    python3 - <<'PY'
import pathlib
path = pathlib.Path("deploy/.env")
if not path.is_file():
    raise SystemExit("deploy/.env missing")
updates = {
    "SCHEDULED_PRIORITY_PIPELINE_ENABLED": "true",
    "SCHEDULED_PRIORITY_PIPELINE_LIMIT": "75",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_HOUR": "*/2",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_MINUTE": "20",
    "WA_STATEWIDE_ROLLOUT_ENABLED": "false",
}
lines = path.read_text(encoding="utf-8").splitlines()
keys = set(updates)
out, seen = [], set()
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in keys:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
missing = [k for k in keys if k not in seen]
if missing:
    out.append("")
    out.append("# Top-parcel priority (enable-priority-pipeline)")
    for k in sorted(missing):
        out.append(f"{k}={updates[k]}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
for k, v in sorted(updates.items()):
    print(f"Set {k}={v}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps worker beat
    ;;
  enable-wa-statewide-rollout)
    echo "=== enable WA statewide rollout (one county/day via WaTech) ==="
    python3 - <<'PY'
import pathlib

path = pathlib.Path("deploy/.env")
if not path.is_file():
    raise SystemExit("deploy/.env missing")

updates = {
    "WA_STATEWIDE_ROLLOUT_ENABLED": "true",
    "WA_STATEWIDE_ROLLOUT_CONFIG_PATH": "/app/config/wa_statewide_rollout.yaml",
    "WA_STATEWIDE_ROLLOUT_CRONTAB_HOUR": "7",
    "WA_STATEWIDE_ROLLOUT_CRONTAB_MINUTE": "15",
}
lines = path.read_text(encoding="utf-8").splitlines()
keys = set(updates)
out: list[str] = []
seen: set[str] = set()
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in keys:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
missing = [k for k in keys if k not in seen]
if missing:
    if out and out[-1].strip():
        out.append("")
    out.append("# WA statewide rollout — one new county per day (config/wa_statewide_rollout.yaml)")
    for key in sorted(missing):
        out.append(f"{key}={updates[key]}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
for key, val in sorted(updates.items()):
    print(f"Set {key}={val}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    echo "=== recreate worker + beat ==="
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps api worker beat
    ;;
  prioritize-baltimore-market)
    echo "=== prioritize Baltimore MD (pause WA statewide; priority pipeline on) ==="
    python3 - <<'PY'
import pathlib

path = pathlib.Path("deploy/.env")
if not path.is_file():
    raise SystemExit("deploy/.env missing")

updates = {
    "GEO_MARKETS_CONFIG_PATH": "/app/config/geo_markets.yaml",
    "WA_STATEWIDE_ROLLOUT_ENABLED": "false",
    "SCHEDULED_PRIORITY_PIPELINE_ENABLED": "true",
    "SCHEDULED_PRIORITY_PIPELINE_LIMIT": "75",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_HOUR": "*/2",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_MINUTE": "20",
}
lines = path.read_text(encoding="utf-8").splitlines()
keys = set(updates)
out: list[str] = []
seen: set[str] = set()
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in keys:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
missing = [k for k in keys if k not in seen]
if missing:
    if out and out[-1].strip():
        out.append("")
    out.append("# Baltimore-first market — WA statewide ingest paused")
    for key in sorted(missing):
        out.append(f"{key}={updates[key]}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
for key, val in sorted(updates.items()):
    print(f"Set {key}={val}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps api worker beat
    if [ -n "$KEY" ]; then
      echo "=== POST /internal/ingest/baltimore-city (kickstart city parcels) ==="
      _internal_api_post "/internal/ingest/baltimore-city" \
        '{"max_features":20000,"auto_run_pipeline":true,"max_auto_pipeline":100}' \
        || echo "baltimore-city ingest skipped or failed"
      echo "=== (Baltimore County ingest paused — city only) ==="
      echo "=== POST /internal/pipeline/enqueue-priority?limit=75 ==="
      _internal_api_post "/internal/pipeline/enqueue-priority?limit=75" || true
    fi
    ;;
  baltimore-ingest-now)
    echo "=== POST /internal/ingest/baltimore-city ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/ingest/baltimore-city" \
        '{"max_features":20000,"auto_run_pipeline":true,"max_auto_pipeline":100}' \
        || echo "baltimore-city ingest failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  baltimore-markets-ingest)
    echo "=== POST Baltimore City ingest only (20k cap; county paused) ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/ingest/baltimore-city" \
        '{"max_features":20000,"auto_run_pipeline":true,"max_auto_pipeline":100}'
      _internal_api_post "/internal/pipeline/enqueue-priority?limit=75" || true
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  baltimore-zoning-overlay)
    echo "=== Baltimore Phase B: fetch parcels + zoning, build overlay, merge ==="
    mkdir -p data/baltimore
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    PARCELS="data/baltimore/baltimore_city_parcels.geojson"
    ZONING="data/baltimore/baltimore_city_zoning_districts.geojson"
    OVERLAY="data/baltimore/baltimore_city_zoning_overlay.geojson"
    WORKER_OVERLAY="/app/data/baltimore/baltimore_city_zoning_overlay.geojson"

    echo "=== git pull (scripts + zoning rules on Droplet) ==="
    git pull --ff-only 2>/dev/null || true

    export PYTHONPATH="${ROOT}/services/ingestion${PYTHONPATH:+:$PYTHONPATH}"

    echo "=== fetch Baltimore City parcels (20k cap) ==="
    python3 scripts/fetch_baltimore_city_parcels.py -o "$PARCELS" --max-features 20000
    echo "=== fetch Baltimore City zoning districts ==="
    python3 scripts/fetch_baltimore_zoning_districts.py -o "$ZONING"

    echo "=== spatial join (API/worker image + mounted ingestion package) ==="
    if ! docker compose -f "$COMPOSE_REL" --env-file deploy/.env ps -q api 2>/dev/null | grep -q .; then
      echo "FAIL: api container not running — cannot build overlay with shapely" >&2
      exit 1
    fi
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env run --rm --no-deps \
      -v "${ROOT}/services/ingestion:/ingestion-mount:ro" \
      -v "${ROOT}/scripts:/scripts-mount:ro" \
      -v "${ROOT}/data:/app/data" \
      -e "PYTHONPATH=/ingestion-mount" \
      worker \
      python3 /scripts-mount/build_baltimore_zoning_overlay.py \
        --parcels "/app/${PARCELS}" \
        --zoning "/app/${ZONING}" \
        -o "/app/${OVERLAY}"

    if [ ! -f "$OVERLAY" ]; then
      echo "FAIL: overlay not found at $OVERLAY" >&2
      exit 1
    fi

    echo "=== validate overlay (dry-run, in container) ==="
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env run --rm --no-deps \
      -v "${ROOT}/services/ingestion:/ingestion-mount:ro" \
      -v "${ROOT}/services/api:/api-mount:ro" \
      -v "${ROOT}/packages/core:/core-mount:ro" \
      -v "${ROOT}/scripts:/scripts-mount:ro" \
      -v "${ROOT}/config:/app/config:ro" \
      -v "${ROOT}/data:/app/data:ro" \
      -e "PYTHONPATH=/ingestion-mount:/api-mount:/core-mount" \
      worker \
      python3 /scripts-mount/validate_phase_b_overlay.py "/app/${OVERLAY}" || true

    if [ -n "$KEY" ]; then
      echo "=== POST merge-geojson-attributes ==="
      _internal_api_post_via_container "/internal/ingest/merge-geojson-attributes" \
        "{\"path\":\"${WORKER_OVERLAY}\",\"refresh_pipeline\":true,\"max_pipeline\":200}" \
        || _internal_api_post "/internal/ingest/merge-geojson-attributes" \
          "{\"path\":\"${WORKER_OVERLAY}\",\"refresh_pipeline\":true,\"max_pipeline\":200}" \
          || echo "merge failed"
      echo "=== enqueue priority pipeline (Baltimore) ==="
      _internal_api_post "/internal/pipeline/enqueue-priority?limit=75" || true
    else
      echo "INTERNAL_API_KEY not set — overlay built at ${OVERLAY}; merge skipped"
    fi
    ;;
  pilot-scope-snapshot)
    echo "=== GET /internal/stats/pilot-scope ==="
    if [ -n "$KEY" ]; then
      _internal_api_get "/internal/stats/pilot-scope" || echo "pilot-scope failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  enable-slow-statewide-expansion)
    echo "=== enable slow statewide expansion (7d/county + keep priority pipeline) ==="
    python3 - <<'PY'
import pathlib

path = pathlib.Path("deploy/.env")
if not path.is_file():
    raise SystemExit("deploy/.env missing")

updates = {
    "GEO_MARKETS_CONFIG_PATH": "/app/config/geo_markets.yaml",
    "WA_STATEWIDE_ROLLOUT_ENABLED": "true",
    "WA_STATEWIDE_ROLLOUT_CONFIG_PATH": "/app/config/wa_statewide_rollout.yaml",
    "WA_STATEWIDE_ROLLOUT_CRONTAB_HOUR": "7",
    "WA_STATEWIDE_ROLLOUT_CRONTAB_MINUTE": "15",
    "SCHEDULED_PRIORITY_PIPELINE_ENABLED": "true",
    "SCHEDULED_PRIORITY_PIPELINE_LIMIT": "75",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_HOUR": "*/2",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_MINUTE": "20",
    "SCHEDULED_ENQUEUE_UNSCORED_LIMIT": "75",
}
lines = path.read_text(encoding="utf-8").splitlines()
keys = set(updates)
out: list[str] = []
seen: set[str] = set()
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in keys:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
missing = [k for k in keys if k not in seen]
if missing:
    if out and out[-1].strip():
        out.append("")
    out.append("# Slow statewide expansion — WaTech 1 county/day; priority pipeline stays on")
    for key in sorted(missing):
        out.append(f"{key}={updates[key]}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
for key, val in sorted(updates.items()):
    print(f"Set {key}={val}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    echo "=== recreate worker + beat ==="
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps api worker beat
    echo "=== rollout status (before kickstart) ==="
    if [ -n "$KEY" ]; then
      _internal_api_get "/internal/ingest/wa-rollout-status" || true
    fi
    if [ "${KICKSTART_ROLLOUT:-true}" = "true" ] && [ -n "$KEY" ]; then
      echo "=== POST /internal/ingest/wa-rollout-now (first/next county if queue OK) ==="
      _internal_api_post "/internal/ingest/wa-rollout-now" || echo "wa-rollout-now skipped or deferred"
    fi
    ;;
  wa-rollout-status)
    echo "=== GET /internal/ingest/wa-rollout-status ==="
    if [ -n "$KEY" ]; then
      _internal_api_get "/internal/ingest/wa-rollout-status" || echo "wa-rollout-status failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  wa-rollout-now)
    echo "=== POST /internal/ingest/wa-rollout-now (enqueue next county) ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/ingest/wa-rollout-now" || echo "wa-rollout-now failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  seed-king-rate-comps)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    echo "=== alembic upgrade heads (ensure parking_rate_comps) ==="
    docker compose "${ARGS[@]}" exec -T api alembic upgrade heads
    echo "=== seed King County parking rate comps ==="
    docker compose "${ARGS[@]}" exec -T api python - <<'PY'
from app.db.session import SessionLocal
from app.rate_comp_seed import seed_king_county_parking_rate_comps

db = SessionLocal()
try:
    result = seed_king_county_parking_rate_comps(db)
    print("seed_king_rate_comps", result)
finally:
    db.close()
PY
    ;;
  enqueue-priority-now)
    echo "=== POST /internal/pipeline/enqueue-priority?limit=75 ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/pipeline/enqueue-priority?limit=75" || echo "enqueue-priority failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  refresh-rate-comp-scores)
    LIMIT="${REFRESH_RATE_COMP_LIMIT:-500}"
    COUNTY="${REFRESH_RATE_COMP_COUNTY:-53033}"
    echo "=== POST /internal/metrics/refresh-rate-comp-scores?limit=${LIMIT}&county_fips=${COUNTY} ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/metrics/refresh-rate-comp-scores?limit=${LIMIT}&county_fips=${COUNTY}" \
        || echo "refresh-rate-comp-scores failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  corner-lot-stats)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    echo "=== corner lot counts (Postgres) ==="
    docker compose "${ARGS[@]}" exec -T api python - <<'PY'
from sqlalchemy import func, select

from app.db.models import Parcel
from app.db.session import SessionLocal

db = SessionLocal()
try:
    total = int(db.scalar(select(func.count()).select_from(Parcel)) or 0)
    corner = int(db.scalar(select(func.count()).where(Parcel.is_corner_lot.is_(True))) or 0)
    king_total = int(
        db.scalar(select(func.count()).where(Parcel.county_fips == "53033")) or 0
    )
    king_corner = int(
        db.scalar(
            select(func.count()).where(
                Parcel.county_fips == "53033",
                Parcel.is_corner_lot.is_(True),
            )
        )
        or 0
    )
    print("corner_lot_stats", {
        "parcels_total": total,
        "parcels_is_corner_lot_true": corner,
        "pct_corner": round(100.0 * corner / total, 4) if total else 0.0,
        "king_county_total": king_total,
        "king_county_corner": king_corner,
        "note": (
            "is_corner_lot is set only when ingest/merge GeoJSON has IS_CORNER or is_corner=true; "
            "WaTech statewide parcels do not include that field by default."
        ),
    })
finally:
    db.close()
PY
    ;;
  fix-hourly-slack-reports)
    echo "=== set hourly Slack digest + site watchdog in deploy/.env ==="
    python3 - <<'PY'
import pathlib

path = pathlib.Path("deploy/.env")
if not path.is_file():
    raise SystemExit("deploy/.env missing")

updates = {
    "SLACK_DIGEST_CRONTAB_MINUTE": "0",
    "SLACK_DIGEST_CRONTAB_HOUR": "*",
    "SLACK_DIGEST_WINDOW_HOURS": "1",
    "SITE_WATCHDOG_HEARTBEAT_HOURS": "1",
    "SITE_WATCHDOG_CRONTAB_MINUTE": "0",
}
lines = path.read_text(encoding="utf-8").splitlines()
keys = set(updates)
out: list[str] = []
seen: set[str] = set()
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in keys:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
missing = [k for k in keys if k not in seen]
if missing:
    if out and out[-1].strip():
        out.append("")
    out.append("# Hourly Slack standup + site watchdog (fix-hourly-slack-reports)")
    for key in sorted(missing):
        out.append(f"{key}={updates[key]}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
for key, val in sorted(updates.items()):
    print(f"Set {key}={val}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    echo "=== recreate worker-slack + beat (hourly schedules; requires current API image) ==="
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps worker-slack beat
    ;;
  fix-watchdog-env)
    echo "=== ensure SITE_WATCHDOG_UI_BASE_URL in deploy/.env ==="
    python3 - <<'PY'
import pathlib

path = pathlib.Path("deploy/.env")
if not path.is_file():
    raise SystemExit("deploy/.env missing")

lines = path.read_text(encoding="utf-8").splitlines()
values = {}
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, val = line.split("=", 1)
    values[key.strip()] = val.strip().strip('"')

ui = values.get("SITE_WATCHDOG_UI_BASE_URL", "")
if not ui:
    ui = values.get("UI_HOST", "")
    if ui and not ui.startswith("http"):
        ui = f"https://{ui}"
if not ui:
    cors = values.get("CORS_ALLOW_ORIGINS", "")
    ui = cors.split(",")[0].strip() if cors else ""

if not ui:
    raise SystemExit("Could not derive UI URL — set SITE_WATCHDOG_UI_BASE_URL or UI_HOST in deploy/.env")

key = "SITE_WATCHDOG_UI_BASE_URL"
new_line = f"{key}={ui}"
found = False
out: list[str] = []
for line in lines:
    if line.startswith(f"{key}="):
        out.append(new_line)
        found = True
    else:
        out.append(line)
if not found:
    if out and out[-1].strip():
        out.append("")
    out.append("# Site watchdog operator UI (auto-set by fix-watchdog-env)")
    out.append(new_line)
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print(f"Set {key}={ui}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    echo "=== recreate worker-slack + beat (pick up watchdog env) ==="
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps worker-slack beat
    ;;
  *)
    echo "Unknown mode: $MODE" >&2
    exit 2
    ;;
esac
