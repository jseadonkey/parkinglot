#!/usr/bin/env bash
# Wait for bulk ingest, then apply scope tags, bump worker throughput, enqueue scoring backlog.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TASK_ID="${1:-}"
LOG="${PILOT_FINALIZE_LOG:-${ROOT}/logs/pilot-ingest-finalize.log}"
mkdir -p "$(dirname "$LOG")"

DEPLOY_ENV="${ROOT}/deploy/.env"
if [[ -f "$DEPLOY_ENV" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$DEPLOY_ENV"
  set +a
fi

PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"
COMPOSE=(docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env)

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

ingest_task_active() {
  local tid="${1:-}"
  local active
  active="$("${COMPOSE[@]}" exec -T worker celery -A app.celery_app inspect active 2>/dev/null || true)"
  echo "$active" | grep -F "app.tasks.ingest_geojson_path" | grep -Fq "$tid"
}

find_ingest_task_id() {
  "${COMPOSE[@]}" exec -T worker celery -A app.celery_app inspect active 2>/dev/null \
    | grep -F "app.tasks.ingest_geojson_path" \
    | grep -oE "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" \
    | head -1 || true
}

if [[ -z "$TASK_ID" ]]; then
  log "Finding active ingest_geojson_path task…"
  TASK_ID="$(find_ingest_task_id)"
fi

if [[ -z "$TASK_ID" ]]; then
  log "No active ingest task — assuming load already finished."
else
  log "Watching ingest task $TASK_ID (poll every 60s)…"
  while ingest_task_active "$TASK_ID"; do
    TOTAL="$(
      "${COMPOSE[@]}" exec -T api python3 -c \
        "from sqlalchemy import create_engine,text;import os;e=create_engine(os.environ['DATABASE_URL']);
with e.connect() as c: print(c.execute(text('select count(*) from parcels where pilot_in_scope')).scalar())" \
        2>/dev/null || echo "?"
    )"
    log "Still ingesting… in-scope parcels visible in DB: $TOTAL"
    sleep 60
  done
  log "Ingest task $TASK_ID finished."
fi

log "Applying pilot scope tags…"
"${COMPOSE[@]}" exec -T api python3 /app/scripts/apply_pilot_scope.py 2>&1 | tee -a "$LOG"

TURBO="${CELERY_WORKER_CONCURRENCY:-4}"
log "Restarting worker with concurrency=$TURBO for scoring backlog…"
CELERY_WORKER_CONCURRENCY="$TURBO" "${COMPOSE[@]}" up -d worker beat 2>&1 | tee -a "$LOG"

log "Enqueue incomplete pipelines (entitlement or strategic missing), batches of 500…"
API_BASE="${PUBLIC_API_URL:-https://api.vspecialist.com}"
STREAK=0
for _ in $(seq 1 400); do
  RESP="$(
    curl -sS -k -X POST "${API_BASE%/}/internal/pipeline/enqueue-incomplete?limit=500" \
      -H "X-Internal-Key: ${INTERNAL_API_KEY}" \
      -H "Content-Type: application/json" || echo '{"enqueued":0}'
  )"
  ENQ="$("$PY" -c "import json,sys; d=json.loads(sys.argv[1]); print(int(d.get('enqueued',0)))" "$RESP" 2>/dev/null || echo 0)"
  log "Batch enqueue: $ENQ parcels"
  if [[ "$ENQ" -eq 0 ]]; then
    STREAK=$((STREAK + 1))
    [[ "$STREAK" -ge 3 ]] && break
  else
    STREAK=0
  fi
  sleep 2
done

log "Done. Operator home page should show scoring backlog climbing — refresh in an hour."
