#!/usr/bin/env bash
# Background: keep enqueueing run_pipeline for parcels missing scores while bulk ingest runs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="${PILOT_PIPELINE_ENQUEUE_LOG:-${ROOT}/logs/pilot-pipeline-enqueue.log}"
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

API_BASE="${PUBLIC_API_URL:-https://api.vspecialist.com}"
INTERVAL="${PILOT_PIPELINE_ENQUEUE_INTERVAL_SEC:-120}"
BATCH="${PILOT_PIPELINE_ENQUEUE_BATCH:-500}"
MAX_ROUNDS="${PILOT_PIPELINE_ENQUEUE_MAX_ROUNDS:-2000}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

CURL=(curl -sS)
if [[ "${PILOT_STRICT_TLS:-0}" != "1" ]] && [[ "$API_BASE" == https://* ]]; then
  CURL+=(-k)
fi

log "Pipeline enqueue loop started (batch=$BATCH interval=${INTERVAL}s max_rounds=$MAX_ROUNDS)"

STREAK=0
for round in $(seq 1 "$MAX_ROUNDS"); do
  if [[ -f "${ROOT}/logs/pilot-chunk-ingest.stop-enqueue" ]]; then
    log "Stop flag seen — exiting enqueue loop."
    exit 0
  fi
  RESP="$(
    "${CURL[@]}" -X POST "${API_BASE%/}/internal/pipeline/enqueue-incomplete?limit=${BATCH}" \
      -H "X-Internal-Key: ${INTERNAL_API_KEY}" \
      -H "Content-Type: application/json" 2>/dev/null || echo '{"enqueued":0}'
  )"
  ENQ="$("$PY" -c "import json,sys; d=json.loads(sys.argv[1]); print(int(d.get('enqueued',0)))" "$RESP" 2>/dev/null || echo 0)"
  log "round=$round enqueued=$ENQ"
  if [[ "$ENQ" -eq 0 ]]; then
    STREAK=$((STREAK + 1))
    if [[ "$STREAK" -ge 5 ]]; then
      log "Five empty rounds — sleeping longer but continuing (ingest may still be running)."
      STREAK=0
      sleep "$((INTERVAL * 2))"
      continue
    fi
  else
    STREAK=0
  fi
  sleep "$INTERVAL"
done

log "Max rounds reached — enqueue loop exiting."
