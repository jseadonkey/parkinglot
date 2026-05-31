#!/usr/bin/env bash
# Split pilot GeoJSON into chunks, stagger parallel ingest, score while loading.
#
# Goal: visible DB progress + parcels reaching full scores without waiting for all 125k.
#
#   cd /opt/workspaces/parkinglot
#   set -a && source deploy/.env && set +a
#   ./scripts/run_pilot_chunk_ingest.sh
#
# Optional env:
#   PILOT_INGEST_PATH          — source GeoJSON (default data/pilot/kent_pilot_candidates.geojson)
#   PILOT_CHUNK_SIZE           — default 10500
#   PILOT_MAX_IN_FLIGHT_INGEST — default 3 (leave 1 worker slot for pipelines on concurrency=4)
#   PILOT_SKIP_SPLIT=1         — reuse existing data/pilot/chunks/manifest.json
#   PILOT_DRY_RUN=1            — split only, do not POST ingest
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="${PILOT_CHUNK_INGEST_LOG:-${ROOT}/logs/pilot-chunk-ingest.log}"
mkdir -p "$(dirname "$LOG")"
rm -f "${ROOT}/logs/pilot-chunk-ingest.stop-enqueue"

DEPLOY_ENV="${ROOT}/deploy/.env"
if [[ -f "$DEPLOY_ENV" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$DEPLOY_ENV"
  set +a
fi

: "${PILOT_INGEST_PATH:=${ROOT}/data/pilot/kent_pilot_candidates.geojson}"
: "${PILOT_CHUNK_DIR:=${ROOT}/data/pilot/chunks}"
: "${PILOT_CHUNK_SIZE:=10500}"
: "${PILOT_MAX_IN_FLIGHT_INGEST:=3}"
: "${PILOT_CHUNK_FROM:=1}"
: "${PUBLIC_API_URL:=https://api.vspecialist.com}"

PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"
COMPOSE=(docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env)

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG"; }
say() { log "$@"; echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

if [[ -z "${INTERNAL_API_KEY:-}" ]]; then
  echo "error: INTERNAL_API_KEY required." >&2
  exit 2
fi

if [[ ! -f "$PILOT_INGEST_PATH" ]]; then
  echo "error: missing $PILOT_INGEST_PATH — run funnel first." >&2
  exit 1
fi

MANIFEST="${PILOT_CHUNK_DIR}/manifest.json"

if [[ "${PILOT_SKIP_SPLIT:-0}" != "1" ]]; then
  log "Splitting $PILOT_INGEST_PATH into chunks of $PILOT_CHUNK_SIZE…"
  "$PY" scripts/split_pilot_geojson.py \
    -i "$PILOT_INGEST_PATH" \
    -o "$PILOT_CHUNK_DIR" \
    --chunk-size "$PILOT_CHUNK_SIZE" 2>&1 | tee -a "$LOG"
else
  log "PILOT_SKIP_SPLIT=1 — using existing manifest."
fi

if [[ ! -f "$MANIFEST" ]]; then
  echo "error: missing $MANIFEST" >&2
  exit 1
fi

CHUNK_COUNT="$("$PY" -c "import json; print(json.load(open('$MANIFEST'))['chunk_count'])")"
log "Chunks ready: $CHUNK_COUNT (manifest $MANIFEST)"

TURBO="${CELERY_WORKER_CONCURRENCY:-4}"
log "Ensuring worker concurrency=$TURBO…"
CELERY_WORKER_CONCURRENCY="$TURBO" "${COMPOSE[@]}" up -d worker beat 2>&1 | tee -a "$LOG"

if [[ "${PILOT_DRY_RUN:-0}" == "1" ]]; then
  log "PILOT_DRY_RUN=1 — split complete, exiting."
  exit 0
fi

log "Starting background pipeline enqueue loop…"
nohup "${ROOT}/scripts/enqueue_pipelines_loop.sh" >> "${ROOT}/logs/pilot-pipeline-enqueue.log" 2>&1 &
ENQUEUE_PID=$!
log "Pipeline enqueue PID=$ENQUEUE_PID"

API_BASE="${PUBLIC_API_URL%/}"

CURL=(curl -sS)
if [[ "${PILOT_STRICT_TLS:-0}" != "1" ]] && [[ "$API_BASE" == https://* ]]; then
  CURL+=(-k)
fi

# POST to internal API (host curl — API container has no curl).
post_internal() {
  local path="$1"
  local body="$2"
  "${CURL[@]}" -f -X POST "${API_BASE}${path}" \
    -H "X-Internal-Key: ${INTERNAL_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$body"
}

count_active_ingest() {
  "${COMPOSE[@]}" exec -T worker celery -A app.celery_app inspect active 2>/dev/null \
    < /dev/null | grep -c "app.tasks.ingest_geojson_path" || true
}

poll_task() {
  local tid="$1"
  local max_sec="${2:-7200}"
  "${ROOT}/scripts/poll_internal_celery_task.sh" "$tid" "$max_sec" >> "$LOG" 2>&1
}

submit_chunk() {
  local container_path="$1"
  local idx="$2"
  local body
  body="$(
    "$PY" - <<PY
import json
print(json.dumps({
    "path": "${container_path}",
    "default_county_fips": "53033",
    "auto_run_pipeline": False,
    "max_auto_pipeline": 1,
}))
PY
  )"
  say "Submitting chunk $idx: $container_path" >&2
  RESP="$(post_internal "/internal/ingest/geojson-server-path" "$body")"
  log "Chunk $idx response: $RESP"
  TASK_ID="$("$PY" -c "import json,sys; print(json.load(sys.stdin).get('task_id',''))" <<< "$RESP")"
  if [[ -z "$TASK_ID" ]]; then
    log "ERROR: no task_id for chunk $idx"
    return 1
  fi
  printf '%s' "$TASK_ID"
}

declare -a TASK_IDS=()

log "Staggered ingest (max $PILOT_MAX_IN_FLIGHT_INGEST in flight on concurrency=$TURBO worker)…"

CHUNK_LINES="$("$PY" -c "import json; m=json.load(open('${MANIFEST}')); s=int('${PILOT_CHUNK_FROM}'); [print(json.dumps(c)) for c in m['chunks'] if c['index']>=s]")"

while IFS= read -r line; do
  IDX="$(echo "$line" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['index'])")"
  CPATH="$(echo "$line" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['container_path'])")"
  FCOUNT="$(echo "$line" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['feature_count'])")"

  while true; do
    ACTIVE="$(count_active_ingest)"
    ACTIVE="${ACTIVE//[^0-9]/}"
    ACTIVE="${ACTIVE:-0}"
    if [[ "$ACTIVE" -lt "$PILOT_MAX_IN_FLIGHT_INGEST" ]]; then
      break
    fi
    log "In-flight ingest=$ACTIVE — waiting 45s before chunk $IDX ($FCOUNT features)…"
    sleep 45
  done

  TID="$(submit_chunk "$CPATH" "$IDX")"
  TASK_IDS+=("$TID")

  IN_SCOPE="$(
    "${COMPOSE[@]}" exec -T api python3 -c \
      "from sqlalchemy import create_engine,text;import os;e=create_engine(os.environ['DATABASE_URL']);
with e.connect() as c: print(c.execute(text('select count(*) from parcels where pilot_in_scope')).scalar())" \
      2>/dev/null < /dev/null || echo "?"
  )"
  say "Queued chunk $IDX — in-scope parcels in DB now: $IN_SCOPE"
done <<< "$CHUNK_LINES"

say "All ${#TASK_IDS[@]} ingest tasks submitted. Waiting for completion…"
FAIL=0
for tid in "${TASK_IDS[@]}"; do
  if ! poll_task "$tid" 14400; then
    log "WARNING: task $tid failed or timed out"
    FAIL=$((FAIL + 1))
  fi
done

log "Ingest tasks finished (failures=$FAIL). Applying pilot scope…"
"${COMPOSE[@]}" exec -T api python3 /app/scripts/apply_pilot_scope.py 2>&1 | tee -a "$LOG"

touch "${ROOT}/logs/pilot-chunk-ingest.stop-enqueue"
log "Signaled pipeline enqueue loop to stop (PID $ENQUEUE_PID)."

log "Final pipeline drain (batches of 500)…"
STREAK=0
for _ in $(seq 1 200); do
  RESP="$(post_internal "/internal/pipeline/enqueue-incomplete?limit=500" "{}")" || RESP='{"enqueued":0}'
  ENQ="$("$PY" -c "import json,sys; d=json.loads(sys.argv[1]); print(int(d.get('enqueued',0)))" "$RESP" 2>/dev/null || echo 0)"
  log "Final enqueue: $ENQ"
  if [[ "$ENQ" -eq 0 ]]; then
    STREAK=$((STREAK + 1))
    [[ "$STREAK" -ge 3 ]] && break
  else
    STREAK=0
  fi
  sleep 2
done

TOTAL="$(
  "${COMPOSE[@]}" exec -T api python3 -c \
    "from sqlalchemy import create_engine,text;import os;e=create_engine(os.environ['DATABASE_URL']);
with e.connect() as c:
  t=c.execute(text('select count(*) from parcels')).scalar()
  s=c.execute(text('select count(*) from parcels where pilot_in_scope')).scalar()
  print(f'total={t} in_scope={s}')" 2>/dev/null || echo "?"
)"
log "Done. Parcels: $TOTAL"
log "Check https://vspecialist.com/operator and /operator/deals for scored parcels."
