#!/usr/bin/env bash
# Execute Phase A (scores + demand distance + readiness) against a deployed stack.
#
# Requires on the host running this script:
#   DATABASE_URL   — same Postgres URL as the API (for CLI gap counts)
#
# Optional (HTTP steps — enqueue incomplete pipelines + refresh demand distances):
#   PHASE_A_API_BASE     — default http://127.0.0.1:8000 (inside api container: http://127.0.0.1:8000)
#   INTERNAL_API_KEY     — must match deploy/.env if the API enforces X-Internal-Key
#
# Optional tuning:
#   PHASE_A_ENQUEUE_LIMIT       — default 500 (POST .../pipeline/enqueue-incomplete)
#   PHASE_A_DEMAND_LIMIT        — default 2000 (refresh-demand-distances)
#   PHASE_A_COUNTY_FIPS         — e.g. 53033 — limit demand refresh to one county
#   PHASE_A_SKIP_HTTP=1       — only run CLI readiness (no curl to API)
#   PHASE_A_WAIT_SEC=30       — sleep before final readiness (let Celery start)
#   PHASE_A_EXPORT_PATH       — if set, run export_scored_parcels_csv.py -o "$PHASE_A_EXPORT_PATH"
#   PHASE_A_PUBLISH_SPACES=1  — add --publish-spaces to export (needs STORAGE_*)
#
# Droplet (repo at /opt/workspaces/parkinglot, compose from deploy/):
#   set -a && source deploy/.env && set +a
#   export DATABASE_URL INTERNAL_API_KEY
#   ./scripts/execute-phase-a.sh
#
# Or from API container (Python + curl available; DB URL must reach Postgres):
#   docker compose -f deploy/docker-compose.production.yml exec -T api \
#     bash -lc 'export DATABASE_URL="$DATABASE_URL" INTERNAL_API_KEY="$INTERNAL_API_KEY" && /app/scripts/execute-phase-a.sh'
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${PHASE_A_ENQUEUE_LIMIT:=500}"
: "${PHASE_A_DEMAND_LIMIT:=2000}"
: "${PHASE_A_API_BASE:=http://127.0.0.1:8000}"
: "${PHASE_A_WAIT_SEC:=30}"
: "${PHASE_A_SKIP_HTTP:=0}"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL is not set (same URL the API uses)." >&2
  exit 2
fi

echo "=== Phase A — export readiness (before) ==="
"$PY" "${ROOT}/scripts/check_export_readiness.py"
echo

if [[ "$PHASE_A_SKIP_HTTP" == "1" ]]; then
  echo "PHASE_A_SKIP_HTTP=1 — skipping HTTP enqueue + demand refresh."
  exit 0
fi

KEY_HEADER=()
if [[ -n "${INTERNAL_API_KEY:-}" ]]; then
  KEY_HEADER=(-H "X-Internal-Key: ${INTERNAL_API_KEY}")
else
  echo "warning: INTERNAL_API_KEY unset — if production enforces it, these curls may return 401." >&2
fi

BASE="${PHASE_A_API_BASE%/}"

echo "=== POST ${BASE}/internal/pipeline/enqueue-incomplete (limit=${PHASE_A_ENQUEUE_LIMIT}) ==="
ENC_RESP="$(curl -sS "${KEY_HEADER[@]}" -X POST \
  "${BASE}/internal/pipeline/enqueue-incomplete?limit=${PHASE_A_ENQUEUE_LIMIT}" \
  -H "Accept: application/json" || true)"
echo "$ENC_RESP"
echo

DEM_URL="${BASE}/internal/metrics/refresh-demand-distances?limit=${PHASE_A_DEMAND_LIMIT}"
if [[ -n "${PHASE_A_COUNTY_FIPS:-}" ]]; then
  DEM_URL+="&county_fips=${PHASE_A_COUNTY_FIPS}"
fi

echo "=== POST ${DEM_URL} ==="
DEM_RESP="$(curl -sS "${KEY_HEADER[@]}" -X POST "$DEM_URL" -H "Accept: application/json" || true)"
echo "$DEM_RESP"
TASK_ID="$(echo "$DEM_RESP" | "${PY}" -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || true)"
if [[ -n "$TASK_ID" ]]; then
  echo
  echo "Demand refresh task_id: $TASK_ID — poll: GET ${BASE}/internal/tasks/${TASK_ID}"
fi
echo

if [[ "${PHASE_A_WAIT_SEC}" =~ ^[0-9]+$ ]] && [[ "$PHASE_A_WAIT_SEC" -gt 0 ]]; then
  echo "Waiting ${PHASE_A_WAIT_SEC}s for workers to start processing..."
  sleep "$PHASE_A_WAIT_SEC"
fi

echo "=== Phase A — export readiness (after) ==="
"$PY" "${ROOT}/scripts/check_export_readiness.py"
echo

if [[ -n "${PHASE_A_EXPORT_PATH:-}" ]]; then
  echo "=== CSV export → ${PHASE_A_EXPORT_PATH} ==="
  EXP=( "$PY" "${ROOT}/scripts/export_scored_parcels_csv.py" -o "$PHASE_A_EXPORT_PATH" )
  if [[ "${PHASE_A_PUBLISH_SPACES:-0}" == "1" ]]; then
    EXP+=( --publish-spaces )
  fi
  "${EXP[@]}"
  echo "Export finished."
fi

echo "Phase A script complete. Re-run readiness later if many pipelines were enqueued; tail worker logs if counts lag."
