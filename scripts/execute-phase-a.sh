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
#   PHASE_A_ENQUEUE_LIMIT       — default 500 (POST .../pipeline/enqueue-incomplete per round)
#   PHASE_A_ENQUEUE_ROUNDS      — default 1 — repeat enqueue N times (drain backlog > limit)
#   PHASE_A_ROUND_SLEEP         — seconds between enqueue rounds (default 15)
#   PHASE_A_REFRESH_IDENTIFICATION — default 1 — POST .../metrics/refresh-identification-scores
#   PHASE_A_IDENT_LIMIT         — default 2000 (identification backfill batch size)
#   PHASE_A_DEMAND_LIMIT        — default 2000 (refresh-demand-distances)
#   PHASE_A_COUNTY_FIPS         — e.g. 53033 — applies to identification + demand refresh
#   PHASE_A_SKIP_HTTP=1         — only run CLI readiness (no curl to API)
#   PHASE_A_WAIT_SEC            — sleep after HTTP work before final readiness (default 45)
#   PHASE_A_POLL_IDENTIFICATION_TASK=1 — poll identification Celery task until done
#   PHASE_A_POLL_DEMAND_TASK=1  — poll demand-distance Celery task until done
#   PHASE_A_POLL_TIMEOUT_SEC    — max wait per polled task (default 900)
#   PHASE_A_POLL_INTERVAL_SEC   — poll interval (default 5)
#   PHASE_A_EXPORT_PATH         — if set, run export_scored_parcels_csv.py -o "$PHASE_A_EXPORT_PATH"
#   PHASE_A_PUBLISH_SPACES=1    — add --publish-spaces to export (needs STORAGE_*)
#   PHASE_A_JSON_DIR            — if set, write before/after readiness JSON here (mkdir -p)
#
# Droplet (repo at /opt/workspaces/parkinglot, compose from deploy/):
#   set -a && source deploy/.env && set +a
#   export DATABASE_URL INTERNAL_API_KEY
#   PHASE_A_API_BASE="https://YOUR_PUBLIC_API" PHASE_A_ENQUEUE_ROUNDS=3 ./scripts/execute-phase-a.sh
#
# Or from API container:
#   docker compose -f deploy/docker-compose.production.yml exec -T api \
#     bash -lc 'export DATABASE_URL INTERNAL_API_KEY PHASE_A_API_BASE=http://127.0.0.1:8000 && /app/scripts/execute-phase-a.sh'
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${PHASE_A_ENQUEUE_LIMIT:=500}"
: "${PHASE_A_ENQUEUE_ROUNDS:=1}"
: "${PHASE_A_ROUND_SLEEP:=15}"
: "${PHASE_A_DEMAND_LIMIT:=2000}"
: "${PHASE_A_API_BASE:=http://127.0.0.1:8000}"
: "${PHASE_A_WAIT_SEC:=45}"
: "${PHASE_A_SKIP_HTTP:=0}"
: "${PHASE_A_REFRESH_IDENTIFICATION:=1}"
: "${PHASE_A_IDENT_LIMIT:=2000}"
: "${PHASE_A_POLL_IDENTIFICATION_TASK:=0}"
: "${PHASE_A_POLL_DEMAND_TASK:=0}"
: "${PHASE_A_POLL_TIMEOUT_SEC:=900}"
: "${PHASE_A_POLL_INTERVAL_SEC:=5}"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

json_state() {
  echo "$1" | "${PY}" -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || echo ""
}

poll_until_done() {
  local tid="$1"
  local label="$2"
  [[ -z "$tid" ]] && return 0
  echo "Polling \"${label}\" until SUCCESS/FAILURE (timeout ${PHASE_A_POLL_TIMEOUT_SEC}s)..."
  local elapsed=0
  while [[ "$elapsed" -lt "$PHASE_A_POLL_TIMEOUT_SEC" ]]; do
    local POLL STATE
    POLL="$(curl -sS "${KEY_HEADER[@]}" "${BASE}/internal/tasks/${tid}" -H "Accept: application/json" || echo "{}")"
    STATE="$(json_state "$POLL")"
    if [[ "$STATE" == "SUCCESS" ]]; then
      echo "\"${label}\" SUCCESS (${elapsed}s)."
      echo "$POLL" | "${PY}" -m json.tool 2>/dev/null || echo "$POLL"
      echo
      return 0
    fi
    if [[ "$STATE" == "FAILURE" ]]; then
      echo "\"${label}\" FAILURE:" >&2
      echo "$POLL" | "${PY}" -m json.tool 2>/dev/null || echo "$POLL"
      echo
      return 1
    fi
    printf "\r  [%s] state=%s %ss/%ss   " "$label" "${STATE:-UNKNOWN}" "$elapsed" "$PHASE_A_POLL_TIMEOUT_SEC"
    sleep "$PHASE_A_POLL_INTERVAL_SEC"
    elapsed=$((elapsed + PHASE_A_POLL_INTERVAL_SEC))
  done
  echo
  echo "warning: \"${label}\" poll timed out — check worker logs." >&2
  return 2
}

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL is not set (same URL the API uses)." >&2
  exit 2
fi

save_json_if_requested() {
  local label="$1"
  if [[ -z "${PHASE_A_JSON_DIR:-}" ]]; then
    return 0
  fi
  mkdir -p "$PHASE_A_JSON_DIR"
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  "$PY" "${ROOT}/scripts/check_export_readiness.py" --json > "${PHASE_A_JSON_DIR}/readiness-${label}-${ts}.json"
  echo "Wrote ${PHASE_A_JSON_DIR}/readiness-${label}-${ts}.json"
}

echo "=== Phase A — export readiness (before) ==="
"$PY" "${ROOT}/scripts/check_export_readiness.py"
save_json_if_requested before
echo

if [[ "$PHASE_A_SKIP_HTTP" == "1" ]]; then
  echo "PHASE_A_SKIP_HTTP=1 — skipping HTTP steps (enqueue, identification, demand)."
  exit 0
fi

KEY_HEADER=()
if [[ -n "${INTERNAL_API_KEY:-}" ]]; then
  KEY_HEADER=(-H "X-Internal-Key: ${INTERNAL_API_KEY}")
else
  echo "warning: INTERNAL_API_KEY unset — if production enforces it, these curls may return 401." >&2
fi

BASE="${PHASE_A_API_BASE%/}"

for ((round = 1; round <= PHASE_A_ENQUEUE_ROUNDS; round++)); do
  echo "=== POST ${BASE}/internal/pipeline/enqueue-incomplete (round ${round}/${PHASE_A_ENQUEUE_ROUNDS}, limit=${PHASE_A_ENQUEUE_LIMIT}) ==="
  ENC_RESP="$(curl -sS "${KEY_HEADER[@]}" -X POST \
    "${BASE}/internal/pipeline/enqueue-incomplete?limit=${PHASE_A_ENQUEUE_LIMIT}" \
    -H "Accept: application/json" || true)"
  echo "$ENC_RESP"
  ENQ="$(echo "$ENC_RESP" | "${PY}" -c "import sys,json; print(json.load(sys.stdin).get('enqueued', ''))" 2>/dev/null || true)"
  echo "(enqueued this round: ${ENQ:-?})"
  echo
  if [[ "$round" -lt "$PHASE_A_ENQUEUE_ROUNDS" ]]; then
    echo "Sleep ${PHASE_A_ROUND_SLEEP}s before next enqueue round..."
    sleep "$PHASE_A_ROUND_SLEEP"
  fi
done

IDENT_TASK_ID=""
if [[ "${PHASE_A_REFRESH_IDENTIFICATION}" == "1" ]]; then
  ID_URL="${BASE}/internal/metrics/refresh-identification-scores?limit=${PHASE_A_IDENT_LIMIT}"
  if [[ -n "${PHASE_A_COUNTY_FIPS:-}" ]]; then
    ID_URL+="&county_fips=${PHASE_A_COUNTY_FIPS}"
  fi
  echo "=== POST ${ID_URL} ==="
  ID_RESP="$(curl -sS "${KEY_HEADER[@]}" -X POST "$ID_URL" -H "Accept: application/json" || true)"
  echo "$ID_RESP"
  IDENT_TASK_ID="$(echo "$ID_RESP" | "${PY}" -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || true)"
  if [[ -n "$IDENT_TASK_ID" ]]; then
    echo "Identification refresh task_id: $IDENT_TASK_ID"
    if [[ "${PHASE_A_POLL_IDENTIFICATION_TASK}" == "1" ]]; then
      poll_until_done "$IDENT_TASK_ID" "Identification refresh" || true
    else
      echo "Poll manually: GET ${BASE}/internal/tasks/${IDENT_TASK_ID}"
      echo "(Set PHASE_A_POLL_IDENTIFICATION_TASK=1 to wait.)"
    fi
  fi
  echo
else
  echo "PHASE_A_REFRESH_IDENTIFICATION=0 — skipping identification backfill."
  echo
fi

DEM_URL="${BASE}/internal/metrics/refresh-demand-distances?limit=${PHASE_A_DEMAND_LIMIT}"
if [[ -n "${PHASE_A_COUNTY_FIPS:-}" ]]; then
  DEM_URL+="&county_fips=${PHASE_A_COUNTY_FIPS}"
fi

echo "=== POST ${DEM_URL} ==="
DEM_RESP="$(curl -sS "${KEY_HEADER[@]}" -X POST "$DEM_URL" -H "Accept: application/json" || true)"
echo "$DEM_RESP"
DEM_TASK_ID="$(echo "$DEM_RESP" | "${PY}" -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || true)"

if [[ -n "$DEM_TASK_ID" ]]; then
  echo "Demand refresh task_id: $DEM_TASK_ID"
  if [[ "${PHASE_A_POLL_DEMAND_TASK}" == "1" ]]; then
    poll_until_done "$DEM_TASK_ID" "Demand distance refresh" || true
  else
    echo "Poll manually: GET ${BASE}/internal/tasks/${DEM_TASK_ID}"
    echo "(Set PHASE_A_POLL_DEMAND_TASK=1 to wait automatically.)"
  fi
fi
echo

if [[ "${PHASE_A_WAIT_SEC}" =~ ^[0-9]+$ ]] && [[ "$PHASE_A_WAIT_SEC" -gt 0 ]]; then
  echo "Waiting ${PHASE_A_WAIT_SEC}s before final readiness (pipelines still process in background)..."
  sleep "$PHASE_A_WAIT_SEC"
fi

echo "=== Phase A — export readiness (after) ==="
"$PY" "${ROOT}/scripts/check_export_readiness.py"
save_json_if_requested after
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

echo "Phase A script complete."
echo "If parcels_missing_entitlement_or_strategic is still high, increase PHASE_A_ENQUEUE_ROUNDS or run again later after workers drain."
