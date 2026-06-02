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

    if ! echo "$LAST_DIGEST" | grep -q '"found": true'; then
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
      curl -fsSk --connect-timeout 15 --max-time 60 \
        "$BASE/internal/stats/export-readiness" -H "X-Internal-Key: $KEY" || echo "export-readiness failed"
    else
      echo "INTERNAL_API_KEY not set — skipping export-readiness"
    fi
    echo ""
    echo "=== scoring-summary (funnel counts) ==="
    if [ -n "$KEY" ]; then
      curl -fsSk --connect-timeout 15 --max-time 60 \
        "$BASE/internal/stats/scoring-summary" -H "X-Internal-Key: $KEY" || echo "scoring-summary failed"
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
  *)
    echo "Unknown mode: $MODE" >&2
    exit 2
    ;;
esac
