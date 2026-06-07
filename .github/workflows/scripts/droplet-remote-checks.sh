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

_json_value() {
  local path="$1"
  python3 -c '
import json
import sys

parts = sys.argv[1].split(".") if len(sys.argv) > 1 and sys.argv[1] else []
try:
    data = json.load(sys.stdin)
    for part in parts:
        if isinstance(data, dict):
            data = data.get(part)
        else:
            data = None
            break
    if data is None:
        print("")
    elif isinstance(data, (dict, list)):
        print(json.dumps(data))
    else:
        print(data)
except Exception:
    print("")
' "$path"
}

WAIT_TASK_RESPONSE=""
_wait_internal_task() {
  local task_id="$1"
  local label="$2"
  local timeout="${3:-7200}"
  local interval="${4:-10}"
  local elapsed=0
  local body=""
  local state=""
  WAIT_TASK_RESPONSE=""
  if [ -z "$task_id" ]; then
    echo "FAIL: missing task id for ${label}" >&2
    return 1
  fi
  echo "=== wait for ${label} (${task_id}, timeout ${timeout}s) ==="
  while [ "$elapsed" -le "$timeout" ]; do
    body="$(_internal_api_get "/internal/tasks/${task_id}")"
    state="$(printf '%s' "$body" | _json_value state)"
    if [ "$state" = "SUCCESS" ]; then
      echo "${label} SUCCESS after ${elapsed}s"
      printf '%s\n' "$body" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$body"
      WAIT_TASK_RESPONSE="$body"
      return 0
    fi
    if [ "$state" = "FAILURE" ]; then
      echo "${label} FAILURE after ${elapsed}s" >&2
      printf '%s\n' "$body" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$body"
      WAIT_TASK_RESPONSE="$body"
      return 1
    fi
    printf '  [%s] state=%s elapsed=%ss/%ss\n' "$label" "${state:-UNKNOWN}" "$elapsed" "$timeout"
    sleep "$interval"
    elapsed=$((elapsed + interval))
  done
  echo "FAIL: ${label} timed out after ${timeout}s" >&2
  WAIT_TASK_RESPONSE="$body"
  return 1
}

_baltimore_phase1_status_json() {
  local compose_rel="${COMPOSE_REL:-deploy/docker-compose.production.ghcr.yml}"
  docker compose -f "$compose_rel" --env-file deploy/.env exec -T api python - <<'PY'
import json
import os
import urllib.parse
import urllib.request

from sqlalchemy import create_engine, text

COUNTY = "24510"
SOURCE_LAYER = "https://egis.baltimorecity.gov/egis/rest/services/Parcel_Information/Parcel/FeatureServer/0"


def source_count():
    params = urllib.parse.urlencode({"where": "1=1", "returnCountOnly": "true", "f": "json"})
    req = urllib.request.Request(
        f"{SOURCE_LAYER}/query?{params}",
        headers={"User-Agent": "parking-baltimore-phase1-status/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return int(payload["count"]) if payload.get("count") is not None else None


def pct(num, den):
    return round((num / den) * 100, 2) if den else None


engine = create_engine(os.environ["DATABASE_URL"])
source = source_count()
with engine.connect() as conn:
    row = conn.execute(
        text(
            """
            with latest_ident as (
              select distinct on (s.parcel_id)
                s.parcel_id,
                s.total_score,
                s.created_at
              from parcel_scores s
              join parcels p on p.id = s.parcel_id
              where p.county_fips = :cf
                and s.score_profile = 'identification'
              order by s.parcel_id, s.created_at desc
            )
            select
              count(p.*)::int as parcel_total,
              count(distinct p.apn)::int as distinct_apns,
              (count(p.*) - count(distinct p.apn))::int as duplicate_apn_rows,
              count(p.*) filter (where nullif(trim(p.apn), '') is null)::int as missing_apn,
              count(p.*) filter (where p.footprint is null)::int as missing_footprint,
              count(li.parcel_id)::int as identification_score_count,
              count(p.*) filter (where li.parcel_id is null)::int as missing_identification_score,
              count(li.parcel_id) filter (where li.total_score >= 45)::int as prescreen_qualified_45,
              max(li.created_at)::text as latest_identification_score_at
            from parcels p
            left join latest_ident li on li.parcel_id = p.id
            where p.county_fips = :cf
            """,
        ),
        {"cf": COUNTY},
    ).mappings().one()

parcel_total = int(row["parcel_total"] or 0)
missing_ident = int(row["missing_identification_score"] or 0)
source_gap = max((source or 0) - parcel_total, 0) if source is not None else None
status = {
    "county_fips": COUNTY,
    "source_parcel_count": source,
    "parcel_total": parcel_total,
    "source_gap": source_gap,
    "source_coverage_pct": pct(parcel_total, source),
    "distinct_apns": int(row["distinct_apns"] or 0),
    "duplicate_apn_rows": int(row["duplicate_apn_rows"] or 0),
    "missing_apn": int(row["missing_apn"] or 0),
    "missing_footprint": int(row["missing_footprint"] or 0),
    "identification_score_count": int(row["identification_score_count"] or 0),
    "missing_identification_score": missing_ident,
    "identification_coverage_pct": pct(parcel_total - missing_ident, parcel_total),
    "prescreen_qualified_45": int(row["prescreen_qualified_45"] or 0),
    "latest_identification_score_at": row["latest_identification_score_at"],
    "phase1_complete_for_source": source is not None and source_gap == 0 and missing_ident == 0,
}
print(json.dumps(status, sort_keys=True))
PY
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
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --force-recreate --no-deps api worker worker-slack beat
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
  disk-maintenance)
    echo "=== scheduled disk maintenance (prune + Baltimore staging cleanup) ==="
    if [ -f scripts/remote/droplet-disk-maintenance.sh ]; then
      DISK_MAINTENANCE_AGGRESSIVE="${DISK_MAINTENANCE_AGGRESSIVE:-1}" bash scripts/remote/droplet-disk-maintenance.sh
    else
      echo "FAIL: scripts/remote/droplet-disk-maintenance.sh missing" >&2
      exit 1
    fi
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
    echo "=== pause heavy scheduled DB writers in deploy/.env ==="
    python3 <<'PY'
import pathlib
import re

path = pathlib.Path("deploy/.env")
text = path.read_text(encoding="utf-8")
updates = {
    # Keep watchdog/reporting alive, but stop automatic write-heavy repairs while DB CPU recovers.
    "OPS_REMEDIATION_AUTO_FIX": "false",
    "SCHEDULED_ENQUEUE_UNSCORED_ENABLED": "false",
    "SCHEDULED_PRIORITY_PIPELINE_ENABLED": "false",
    "SCHEDULED_REFRESH_IDENTIFICATION_ENABLED": "false",
    "SCHEDULED_REFRESH_DEMAND_ENABLED": "false",
    "WA_STATEWIDE_ROLLOUT_ENABLED": "false",
    "EXPLORATION_CAMPAIGN_ENABLED": "false",
}
for key, value in updates.items():
    if re.search(rf"^{re.escape(key)}=", text, re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, count=1, flags=re.M)
    else:
        text = text.rstrip() + f"\n{key}={value}\n"
path.write_text(text, encoding="utf-8")
for key, value in updates.items():
    print(f"Set {key}={value}")
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
    echo "Done. Re-enable selected schedulers in deploy/.env and recreate beat when DB CPU is normal."
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
    echo "=== site watchdog server checks (JSON on last line) ==="
    # Disk + compose run on the SSH host (docker CLI is not available inside the api container).
    CONTAINER_CHECKS="$(
      docker compose "${ARGS[@]}" exec -T api python - <<'PY' 2>/dev/null || true
import json
from dataclasses import asdict

from app.config import get_settings
from app.db.session import SessionLocal
from app.site_watchdog import run_server_checks

db = SessionLocal()
try:
    checks = run_server_checks(db, get_settings(), source="github-ssh")
finally:
    db.close()
print(json.dumps([asdict(c) for c in checks]))
PY
    )"
    export COMPOSE_REL
    export CONTAINER_CHECKS
    WATCHDOG_JSON="$(
      python3 <<'PY'
import json
import os
import subprocess
from datetime import UTC, datetime

checks: list[dict] = []

try:
    line = subprocess.check_output(["df", "-h", "/"], text=True).strip().splitlines()[-1]
    parts = line.split()
    use_pct = int(parts[4].rstrip("%")) if len(parts) >= 5 else 100
    checks.append(
        {
            "name": "disk_root",
            "ok": use_pct < 90,
            "detail": line,
            "source": "github-ssh",
        }
    )
except Exception as exc:
    checks.append({"name": "disk_root", "ok": False, "detail": str(exc)[:200], "source": "github-ssh"})

unhealthy: list[str] = []
try:
    rel = os.environ.get("COMPOSE_REL", "deploy/docker-compose.production.ghcr.yml")
    out = subprocess.check_output(
        ["docker", "compose", "-f", rel, "--env-file", "deploy/.env", "ps", "--format", "{{.Name}}:{{.Health}}"],
        text=True,
    )
    for row in out.splitlines():
        h = row.split(":")[-1].lower() if ":" in row else ""
        if h and h not in ("healthy", ""):
            unhealthy.append(row.strip())
    checks.append(
        {
            "name": "compose_health",
            "ok": len(unhealthy) == 0,
            "detail": "ok" if not unhealthy else "; ".join(unhealthy[:8]),
            "source": "github-ssh",
        }
    )
except Exception as exc:
    checks.append({"name": "compose_health", "ok": False, "detail": str(exc)[:200], "source": "github-ssh"})

container = (os.environ.get("CONTAINER_CHECKS") or "").strip()
if container:
    checks.extend(json.loads(container))

failures = [c for c in checks if not c.get("ok")]
print(
    json.dumps(
        {
            "checked_at": datetime.now(tz=UTC).isoformat(),
            "runner": "github-ssh",
            "ok": len(failures) == 0,
            "failure_count": len(failures),
            "checks": checks,
        }
    )
)
PY
    )"
    echo "WATCHDOG_JSON=${WATCHDOG_JSON}"
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
        '{"auto_run_pipeline":true,"max_auto_pipeline":100}' \
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
        '{"auto_run_pipeline":true,"max_auto_pipeline":100}' \
        || echo "baltimore-city ingest failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  baltimore-full-city-phase1)
    echo "=== Baltimore City full Phase 1: all city parcels + identification prescreen ==="
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    export COMPOSE_REL
    if [ -z "$KEY" ]; then
      echo "FAIL: INTERNAL_API_KEY not set" >&2
      exit 1
    fi
    if ! docker compose -f "$COMPOSE_REL" --env-file deploy/.env ps -q api 2>/dev/null | grep -q .; then
      echo "=== starting api/worker/beat ==="
      docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d api worker beat
    fi

    echo "=== Phase 1 status before ==="
    STATUS="$(_baltimore_phase1_status_json)"
    printf '%s\n' "$STATUS" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$STATUS"
    COMPLETE="$(printf '%s' "$STATUS" | _json_value phase1_complete_for_source)"
    if [ "$COMPLETE" = "True" ] || [ "$COMPLETE" = "true" ]; then
      echo "Baltimore City Phase 1 is already complete for full source parcel count."
      exit 0
    fi

    echo "=== POST /internal/ingest/baltimore-city (full city cap 750k; pipeline off) ==="
    FETCH_RESP="$(_internal_api_post "/internal/ingest/baltimore-city" \
      '{"max_features":750000,"auto_run_pipeline":false,"max_auto_pipeline":1}')"
    printf '%s\n' "$FETCH_RESP" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$FETCH_RESP"
    FETCH_TASK_ID="$(printf '%s' "$FETCH_RESP" | _json_value task_id)"
    _wait_internal_task "$FETCH_TASK_ID" "Baltimore full-city fetch" "${BALTIMORE_FULL_CITY_FETCH_TIMEOUT_SEC:-10800}" 15

    INGEST_TASK_ID="$(printf '%s' "$WAIT_TASK_RESPONSE" | _json_value result.ingest_task_id)"
    if [ -z "$INGEST_TASK_ID" ]; then
      echo "FAIL: fetch task did not return ingest_task_id" >&2
      exit 1
    fi
    _wait_internal_task "$INGEST_TASK_ID" "Baltimore full-city ingest" "${BALTIMORE_FULL_CITY_INGEST_TIMEOUT_SEC:-10800}" 15

    echo "=== Phase 1 status after ingest ==="
    STATUS="$(_baltimore_phase1_status_json)"
    printf '%s\n' "$STATUS" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$STATUS"

    MAX_ROUNDS="${BALTIMORE_FULL_CITY_IDENT_ROUNDS:-80}"
    IDENT_TIMEOUT="${BALTIMORE_FULL_CITY_IDENT_TIMEOUT_SEC:-7200}"
    for round in $(seq 1 "$MAX_ROUNDS"); do
      MISSING_IDENT="$(printf '%s' "$STATUS" | _json_value missing_identification_score)"
      if [ "${MISSING_IDENT:-0}" = "0" ]; then
        echo "No missing identification scores remain."
        break
      fi
      echo "=== identification backfill round ${round}/${MAX_ROUNDS}; missing=${MISSING_IDENT} ==="
      IDENT_RESP="$(_internal_api_post "/internal/metrics/refresh-identification-scores?limit=5000&county_fips=24510&process_all=true")"
      printf '%s\n' "$IDENT_RESP" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$IDENT_RESP"
      IDENT_TASK_ID="$(printf '%s' "$IDENT_RESP" | _json_value task_id)"
      _wait_internal_task "$IDENT_TASK_ID" "Baltimore identification backfill round ${round}" "$IDENT_TIMEOUT" 10
      UPDATED="$(printf '%s' "$WAIT_TASK_RESPONSE" | _json_value result.updated)"

      STATUS="$(_baltimore_phase1_status_json)"
      printf '%s\n' "$STATUS" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$STATUS"
      MISSING_AFTER="$(printf '%s' "$STATUS" | _json_value missing_identification_score)"
      if [ "${MISSING_AFTER:-0}" = "0" ]; then
        echo "Identification backfill complete."
        break
      fi
      if [ "${UPDATED:-0}" = "0" ]; then
        echo "FAIL: identification backfill updated 0 rows but ${MISSING_AFTER} are still missing" >&2
        exit 1
      fi
      if [ "$round" = "$MAX_ROUNDS" ]; then
        echo "FAIL: identification backfill still missing ${MISSING_AFTER} rows after ${MAX_ROUNDS} rounds" >&2
        exit 1
      fi
    done

    echo "=== Final Baltimore City Phase 1 status ==="
    STATUS="$(_baltimore_phase1_status_json)"
    printf '%s\n' "$STATUS" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$STATUS"
    COMPLETE="$(printf '%s' "$STATUS" | _json_value phase1_complete_for_source)"
    if [ "$COMPLETE" != "True" ] && [ "$COMPLETE" != "true" ]; then
      echo "FAIL: Baltimore City Phase 1 is not complete for source parcel count" >&2
      exit 1
    fi
    echo "Baltimore City Phase 1 complete for full source parcel count."
    ;;
  baltimore-markets-ingest)
    echo "=== POST Baltimore City full ingest only (county paused) ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/ingest/baltimore-city" \
        '{"auto_run_pipeline":true,"max_auto_pipeline":100}'
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

    echo "=== git fetch latest main on Droplet ==="
    git fetch origin main 2>/dev/null || true
    git merge --ff-only origin/main 2>/dev/null || git pull --ff-only origin main 2>/dev/null || true

    export PYTHONPATH="${ROOT}/services/ingestion${PYTHONPATH:+:$PYTHONPATH}"

    echo "=== fetch Baltimore City parcels (full city) ==="
    python3 scripts/fetch_baltimore_city_parcels.py -o "$PARCELS"
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
      -v "${ROOT}/data:/app/data:ro" \
      -e "PYTHONPATH=/ingestion-mount" \
      worker \
      python3 /scripts-mount/build_baltimore_zoning_overlay.py \
        --parcels "/app/${PARCELS}" \
        --zoning "/app/${ZONING}" \
        -o - > "${ROOT}/${OVERLAY}"

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

    python3 scripts/summarize_baltimore_zoning_tiers.py -i "$OVERLAY" 2>/dev/null || true

    if [ -n "$KEY" ]; then
      echo "=== POST merge-geojson-attributes ==="
      _internal_api_post_via_container "/internal/ingest/merge-geojson-attributes" \
        "{\"path\":\"${WORKER_OVERLAY}\",\"refresh_pipeline\":true,\"max_pipeline\":200}" \
        || _internal_api_post "/internal/ingest/merge-geojson-attributes" \
          "{\"path\":\"${WORKER_OVERLAY}\",\"refresh_pipeline\":true,\"max_pipeline\":200}" \
          || echo "merge failed"
      echo "=== refresh entitlement scores (Baltimore City) ==="
      _internal_api_post "/internal/metrics/refresh-entitlement-scores?limit=5000&county_fips=24510" || true
      echo "=== GET /internal/stats/baltimore-zoning-tiers ==="
      _internal_api_get "/internal/stats/baltimore-zoning-tiers" || true
      echo "=== enqueue priority pipeline (Baltimore) ==="
      _internal_api_post "/internal/pipeline/enqueue-priority?limit=75" || true
    else
      echo "INTERNAL_API_KEY not set — overlay built at ${OVERLAY}; merge skipped"
    fi
    ;;
  baltimore-rescore-zoning)
    echo "=== Baltimore: merge existing overlay + entitlement rescore (no GIS fetch) ==="
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    OVERLAY="data/baltimore/baltimore_city_zoning_overlay.geojson"
    WORKER_OVERLAY="/app/data/baltimore/baltimore_city_zoning_overlay.geojson"
    if [ ! -f "$OVERLAY" ]; then
      echo "FAIL: overlay missing at $OVERLAY — run baltimore-zoning-overlay first" >&2
      exit 1
    fi
    python3 scripts/summarize_baltimore_zoning_tiers.py -i "$OVERLAY" || true
    if [ -n "$KEY" ]; then
      _internal_api_post_via_container "/internal/ingest/merge-geojson-attributes" \
        "{\"path\":\"${WORKER_OVERLAY}\",\"refresh_pipeline\":false,\"max_pipeline\":0}" \
        || _internal_api_post "/internal/ingest/merge-geojson-attributes" \
          "{\"path\":\"${WORKER_OVERLAY}\",\"refresh_pipeline\":false,\"max_pipeline\":0}" \
          || echo "merge failed"
      _internal_api_post "/internal/metrics/refresh-entitlement-scores?limit=5000&county_fips=24510" || true
      _internal_api_get "/internal/stats/baltimore-zoning-tiers" || true
      _internal_api_post "/internal/pipeline/enqueue-priority?limit=75" || true
    else
      echo "INTERNAL_API_KEY not set"
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
    echo "=== enable slow statewide expansion (size-based county cooldown + keep priority pipeline) ==="
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
    out.append("# Slow statewide expansion — WaTech; size-based cooldown between counties; priority pipeline stays on")
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
  seed-baltimore-rate-comps)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    echo "=== alembic upgrade heads (ensure parking_rate_comps + poi column) ==="
    docker compose "${ARGS[@]}" exec -T api alembic upgrade heads
    echo "=== seed Baltimore metro parking rate comps ==="
    docker compose "${ARGS[@]}" exec -T api python - <<'PY'
from app.db.session import SessionLocal
from app.rate_comp_seed import seed_baltimore_parking_rate_comps

db = SessionLocal()
try:
    result = seed_baltimore_parking_rate_comps(db)
    print("seed_baltimore_rate_comps", result)
finally:
    db.close()
PY
    ;;
  ops-remediation-status)
    echo "=== GET /internal/ops/status ==="
    if [ -n "$KEY" ]; then
      _internal_api_get "/internal/ops/status" || echo "ops/status failed"
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  ops-remediation-run-now)
    echo "=== POST /internal/ops/run-now (diagnose + auto-fix) ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/ops/run-now" || echo "ops/run-now failed"
      echo "=== GET /internal/ops/status (after enqueue) ==="
      sleep 5
      _internal_api_get "/internal/ops/status" || true
    else
      echo "INTERNAL_API_KEY not set"
    fi
    ;;
  enable-ops-remediation)
    echo "=== enable ops remediation loop in deploy/.env ==="
    python3 - <<'PY'
import pathlib

path = pathlib.Path("deploy/.env")
if not path.is_file():
    raise SystemExit("deploy/.env missing")

updates = {
    "OPS_REMEDIATION_ENABLED": "true",
    "OPS_REMEDIATION_AUTO_FIX": "true",
    "OPS_REMEDIATION_ALLOW_DB_WRITES": "true",
    "OPS_REMEDIATION_PRIORITY_COUNTY_FIPS": "24510",
    "OPS_REMEDIATION_COOLDOWN_SEC": "3600",
    "OPS_REMEDIATION_POI_BATCH_LIMIT": "50",
    "OPS_REMEDIATION_CRONTAB_HOUR": "*/2",
    "OPS_REMEDIATION_CRONTAB_MINUTE": "15",
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
    out.append("# Ops remediation — Baltimore gaps + worker health (enable-ops-remediation)")
    for key in sorted(missing):
        out.append(f"{key}={updates[key]}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
for key, val in sorted(updates.items()):
    print(f"Set {key}={val}")
PY
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --force-recreate --no-deps api worker worker-slack beat
    echo "=== wait for API ready after env/container refresh ==="
    for i in $(seq 1 30); do
      READY="$(_internal_api_get "/ready" || true)"
      echo "ready_poll=${i} ready=${READY}"
      if printf '%s' "$READY" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
        break
      fi
      sleep 3
    done
    if [ -n "$KEY" ]; then
      echo "=== kickstart ops loop ==="
      _internal_api_post "/internal/ops/run-now" || true
    fi
    ;;
  refresh-baltimore-revenue-signals)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    POI_LIMIT="${POI_LIMIT:-50}"
    DEMAND_LIMIT="${DEMAND_LIMIT:-2000}"
    COUNTY="24510"
    echo "=== alembic upgrade heads ==="
    docker compose "${ARGS[@]}" exec -T api alembic upgrade heads
    echo "=== seed Baltimore rate comps ==="
    docker compose "${ARGS[@]}" exec -T api python - <<'PY'
from app.db.session import SessionLocal
from app.rate_comp_seed import seed_baltimore_parking_rate_comps

db = SessionLocal()
try:
    print("seed_baltimore_rate_comps", seed_baltimore_parking_rate_comps(db))
finally:
    db.close()
PY
    echo "=== refresh demand distances (county ${COUNTY}, process_all) ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/metrics/refresh-demand-distances?limit=${DEMAND_LIMIT}&county_fips=${COUNTY}&process_all=true" \
        || echo "refresh-demand-distances failed"
      echo "=== rescore entitlement (county ${COUNTY}, process_all) ==="
      _internal_api_post "/internal/metrics/refresh-entitlement-scores?limit=${DEMAND_LIMIT}&county_fips=${COUNTY}&process_all=true" \
        || echo "refresh-entitlement-scores failed"
    else
      echo "INTERNAL_API_KEY not set — skipping demand distance refresh"
    fi
    echo "=== refresh POI density (county ${COUNTY}, limit ${POI_LIMIT}) ==="
    if [ -n "$KEY" ]; then
      _internal_api_post "/internal/metrics/refresh-poi-density?limit=${POI_LIMIT}&county_fips=${COUNTY}&only_missing=true" \
        || echo "refresh-poi-density failed"
    else
      echo "INTERNAL_API_KEY not set — skipping POI refresh"
    fi
    echo "=== export-readiness snapshot ==="
    if [ -n "$KEY" ]; then
      _internal_api_get "/internal/stats/export-readiness" || true
    fi
    ;;
  baltimore-address-backfill-agent)
    COMPOSE_REL="${1:-deploy/docker-compose.production.ghcr.yml}"
    export COMPOSE_REL
    ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
    LIMIT="${ADDRESS_BACKFILL_LIMIT:-5000}"
    MAX_BATCHES="${ADDRESS_BACKFILL_MAX_BATCHES:-1}"
    SLEEP_BETWEEN="${ADDRESS_BACKFILL_SLEEP_BETWEEN_SEC:-30}"
    echo "=== Baltimore address backfill agent ==="
    echo "limit=${LIMIT} max_batches=${MAX_BATCHES} sleep_between=${SLEEP_BETWEEN}"
    echo "=== health gate ==="
    if [ -z "$KEY" ]; then
      echo "INTERNAL_API_KEY not set"
      exit 1
    fi
    READY="$(_internal_api_get "/ready" || true)"
    echo "ready=${READY}"
    if ! printf '%s' "$READY" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
      echo "API not ready; skipping address backfill"
      exit 0
    fi
    PARKING_Q="$(docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || echo 999999)"
    SLACK_Q="$(docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || echo 999999)"
    echo "parking_queue=${PARKING_Q} slack_queue=${SLACK_Q}"
    if [ "${PARKING_Q}" != "0" ]; then
      echo "parking queue not empty; skipping address backfill"
      exit 0
    fi
    for i in $(seq 1 "$MAX_BATCHES"); do
      echo "=== batch ${i}/${MAX_BATCHES}: enqueue limit=${LIMIT} ==="
      RESP="$(_internal_api_post "/internal/metrics/backfill-baltimore-addresses?limit=${LIMIT}&dry_run=false" || true)"
      echo "$RESP"
      TASK_ID="$(printf '%s' "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("task_id",""))' 2>/dev/null || true)"
      if [ -z "$TASK_ID" ]; then
        echo "No task id returned; stopping"
        exit 1
      fi
      for poll in $(seq 1 180); do
        sleep 5
        STATUS="$(_internal_api_get "/internal/tasks/${TASK_ID}" || true)"
        STATE="$(printf '%s' "$STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("state",""))' 2>/dev/null || true)"
        READY_STATE="$(printf '%s' "$STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("ready",""))' 2>/dev/null || true)"
        echo "poll=${poll} state=${STATE} ready=${READY_STATE}"
        if [ "$READY_STATE" = "True" ] || [ "$READY_STATE" = "true" ]; then
          echo "$STATUS"
          RESULT_SELECTED="$(printf '%s' "$STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("result") or {}; print(r.get("selected", ""))' 2>/dev/null || true)"
          RESULT_UPDATED="$(printf '%s' "$STATUS" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("result") or {}; print(r.get("updated", ""))' 2>/dev/null || true)"
          if [ "$STATE" != "SUCCESS" ]; then
            echo "batch failed; stopping"
            exit 1
          fi
          if [ "${RESULT_SELECTED:-0}" = "0" ]; then
            echo "No selected rows; Baltimore address backfill appears complete."
            exit 0
          fi
          echo "batch updated=${RESULT_UPDATED}; continuing if configured"
          break
        fi
        if [ "$poll" = "180" ]; then
          echo "Timed out waiting for task ${TASK_ID}"
          exit 1
        fi
      done
      if [ "$i" != "$MAX_BATCHES" ]; then
        sleep "$SLEEP_BETWEEN"
      fi
    done
    echo "=== post-run health ==="
    _internal_api_get "/ready" || true
    docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || true
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
