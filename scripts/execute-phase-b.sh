#!/usr/bin/env bash
# Phase B — zoning / overlay merge into existing parcels (no new inserts).
#
# Stage a GeoJSON whose properties match ingest aliases (ZONING, ZONING_JURISDICTION, …). See
# docs/PHASED-EXECUTION-PLAN-A-E.md — Phase B, and data/zoning/wa/README.md.
#
# Requires on the host running this script:
#   DATABASE_URL   — same Postgres URL as the API (for CLI gap counts)
#   PHASE_B_OVERLAY_PATH — absolute path to GeoJSON readable by the API + worker containers
#                          (e.g. under repo data/ mounted at /app/data/… inside containers).
#
# Optional (HTTP — POST /internal/ingest/merge-geojson-attributes):
#   PHASE_B_API_BASE      — default http://127.0.0.1:8000
#   INTERNAL_API_KEY      — if API enforces X-Internal-Key
#   PHASE_B_DEFAULT_COUNTY_FIPS — passed when overlay rows omit county
#   PHASE_B_REFRESH_PIPELINE — default 1 — enqueue run_pipeline after merge
#   PHASE_B_MAX_PIPELINE  — default 200 (cap on pipeline jobs)
#   PHASE_B_DELETE_AFTER  — default 0 — delete overlay file after merge (worker only)
#   PHASE_B_SKIP_HTTP=1   — only run readiness (no merge POST)
#   PHASE_B_POLL_TASK=1   — wait until Celery merge task SUCCESS/FAILURE
#   PHASE_B_POLL_TIMEOUT_SEC — default 900
#   PHASE_B_POLL_INTERVAL_SEC — default 5
#   PHASE_B_WAIT_SEC      — sleep after merge before final readiness (default 45)
#   PHASE_B_JSON_DIR      — if set, write before/after readiness JSON snapshots
#   PHASE_B_VALIDATE      — default 1 — run validate_phase_b_overlay.py before POST (set 0 to skip)
#   PHASE_B_OVERLAY_VALIDATE_PATH — optional file path for validation only (when PHASE_B_OVERLAY_PATH
#                          is the in-container path e.g. /app/data/... but the validator runs on the host)
#
# Droplet example (overlay at repo data/ → /app/data/... in container; API must see same path):
#   set -a && source deploy/.env && set +a
#   export DATABASE_URL INTERNAL_API_KEY
#   PHASE_B_OVERLAY_PATH=/opt/workspaces/parkinglot/data/zoning/kent_overlay.geojson \
#   PHASE_B_API_BASE="https://YOUR_PUBLIC_API" ./scripts/execute-phase-b.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${PHASE_B_API_BASE:=http://127.0.0.1:8000}"
: "${PHASE_B_REFRESH_PIPELINE:=1}" # 1/true = enqueue pipelines after merge
: "${PHASE_B_MAX_PIPELINE:=200}"
: "${PHASE_B_DELETE_AFTER:=0}"
: "${PHASE_B_SKIP_HTTP:=0}"
: "${PHASE_B_WAIT_SEC:=45}"
: "${PHASE_B_POLL_TASK:=0}"
: "${PHASE_B_POLL_TIMEOUT_SEC:=900}"
: "${PHASE_B_POLL_INTERVAL_SEC:=5}"
: "${PHASE_B_VALIDATE:=1}"

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
  echo "Polling \"${label}\" until SUCCESS/FAILURE (timeout ${PHASE_B_POLL_TIMEOUT_SEC}s)..."
  local elapsed=0
  while [[ "$elapsed" -lt "$PHASE_B_POLL_TIMEOUT_SEC" ]]; do
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
    printf "\r  [%s] state=%s %ss/%ss   " "$label" "${STATE:-UNKNOWN}" "$elapsed" "$PHASE_B_POLL_TIMEOUT_SEC"
    sleep "$PHASE_B_POLL_INTERVAL_SEC"
    elapsed=$((elapsed + PHASE_B_POLL_INTERVAL_SEC))
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
  if [[ -z "${PHASE_B_JSON_DIR:-}" ]]; then
    return 0
  fi
  mkdir -p "$PHASE_B_JSON_DIR"
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  "$PY" "${ROOT}/scripts/check_export_readiness.py" --json > "${PHASE_B_JSON_DIR}/readiness-${label}-${ts}.json"
  echo "Wrote ${PHASE_B_JSON_DIR}/readiness-${label}-${ts}.json"
}

echo "=== Phase B — export readiness (before) ==="
"$PY" "${ROOT}/scripts/check_export_readiness.py"
save_json_if_requested before
echo

if [[ "$PHASE_B_SKIP_HTTP" == "1" ]]; then
  echo "PHASE_B_SKIP_HTTP=1 — skipping merge POST."
  exit 0
fi

OVERLAY="${PHASE_B_OVERLAY_PATH:-}"
if [[ -z "$OVERLAY" ]]; then
  echo "error: PHASE_B_OVERLAY_PATH is not set (absolute path to overlay GeoJSON)." >&2
  exit 2
fi

VALIDATE_PATH="${PHASE_B_OVERLAY_VALIDATE_PATH:-$OVERLAY}"
if [[ "${PHASE_B_VALIDATE}" == "1" ]]; then
  echo "=== Phase B — validate overlay (dry-run, same loader as merge) ==="
  if [[ ! -r "$VALIDATE_PATH" ]]; then
    echo "error: overlay not readable for validation: ${VALIDATE_PATH}" >&2
    echo "hint: set PHASE_B_OVERLAY_VALIDATE_PATH to the host copy if PHASE_B_OVERLAY_PATH is for the container only." >&2
    exit 2
  fi
  "$PY" "${ROOT}/scripts/validate_phase_b_overlay.py" "$VALIDATE_PATH" || exit $?
  echo
fi

KEY_HEADER=()
if [[ -n "${INTERNAL_API_KEY:-}" ]]; then
  KEY_HEADER=(-H "X-Internal-Key: ${INTERNAL_API_KEY}")
else
  echo "warning: INTERNAL_API_KEY unset — if production enforces it, merge curl may return 401." >&2
fi

BASE="${PHASE_B_API_BASE%/}"

REFRESH_JSON="true"
if [[ "${PHASE_B_REFRESH_PIPELINE}" == "0" ]] || [[ "${PHASE_B_REFRESH_PIPELINE,,}" == "false" ]]; then
  REFRESH_JSON="false"
fi

# Build JSON body without requiring jq (Python one-liner for safe escaping).
POST_BODY="$(
  PHASE_B_OVERLAY_PATH="$OVERLAY" \
  PHASE_B_DEFAULT_COUNTY_FIPS="${PHASE_B_DEFAULT_COUNTY_FIPS:-}" \
  PHASE_B_DELETE_AFTER="$PHASE_B_DELETE_AFTER" \
  PHASE_B_MAX_PIPELINE="$PHASE_B_MAX_PIPELINE" \
  REFRESH_JSON="$REFRESH_JSON" \
  "${PY}" - <<'PY'
import json, os
body = {
    "path": os.environ["PHASE_B_OVERLAY_PATH"],
    "delete_after": os.environ.get("PHASE_B_DELETE_AFTER", "0") in ("1", "true", "True"),
    "refresh_pipeline": os.environ.get("REFRESH_JSON", "true").lower() == "true",
    "max_pipeline": int(os.environ.get("PHASE_B_MAX_PIPELINE", "200")),
}
dcf = (os.environ.get("PHASE_B_DEFAULT_COUNTY_FIPS") or "").strip()
if dcf:
    body["default_county_fips"] = dcf
print(json.dumps(body))
PY
)"

echo "=== POST ${BASE}/internal/ingest/merge-geojson-attributes ==="
echo "Body: ${POST_BODY}"
MERGE_RESP="$(curl -sS "${KEY_HEADER[@]}" -X POST \
  "${BASE}/internal/ingest/merge-geojson-attributes" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "$POST_BODY" || true)"
echo "$MERGE_RESP"
TASK_ID="$(echo "$MERGE_RESP" | "${PY}" -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || true)"

if [[ -n "$TASK_ID" ]]; then
  echo "Merge task_id: $TASK_ID"
  if [[ "${PHASE_B_POLL_TASK}" == "1" ]]; then
    poll_until_done "$TASK_ID" "GeoJSON merge" || true
  else
    echo "Poll manually: GET ${BASE}/internal/tasks/${TASK_ID}"
    echo "(Set PHASE_B_POLL_TASK=1 to wait.)"
  fi
else
  echo "warning: no task_id in response — merge may have failed at HTTP layer." >&2
fi
echo

if [[ "${PHASE_B_WAIT_SEC}" =~ ^[0-9]+$ ]] && [[ "$PHASE_B_WAIT_SEC" -gt 0 ]]; then
  echo "Waiting ${PHASE_B_WAIT_SEC}s before final readiness (pipelines may still run)..."
  sleep "$PHASE_B_WAIT_SEC"
fi

echo "=== Phase B — export readiness (after) — check parcels_missing_zoning_code ==="
"$PY" "${ROOT}/scripts/check_export_readiness.py"
save_json_if_requested after
echo

echo "Phase B script complete."
echo "If zoning gaps remain, add coverage in your overlay or zoning rules YAML and merge again."
