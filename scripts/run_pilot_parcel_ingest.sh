#!/usr/bin/env bash
# Pilot parcel ingest — WaTech funnel → GeoJSON → DB ingest → optional pipeline.
#
# Prerequisites (repo root on Droplet):
#   set -a && source deploy/.env && set +a
#   export DATABASE_URL INTERNAL_API_KEY
#   export KENT_ZONING KING_ZONING   # recommended — same as Phase B
#
# Optional:
#   PILOT_FETCH_MAX_SCAN  — cap WaTech rows scanned (debug)
#   PILOT_FETCH_MAX_KEPT  — stop after N kept candidates
#   PILOT_STATS_ONLY=1    — funnel stats only, no file / no ingest
#   PILOT_SKIP_INGEST=1   — write GeoJSON only
#   PILOT_INGEST_PATH     — host path (default data/pilot/kent_pilot_candidates.geojson)
#   PILOT_CONTAINER_PATH  — worker path (default /app/data/pilot/kent_pilot_candidates.geojson)
#   PILOT_AUTO_PIPELINE   — default 1
#   PILOT_MAX_PIPELINE    — default 500
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

DEPLOY_ENV="${ROOT}/deploy/.env"
if [[ -f "$DEPLOY_ENV" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$DEPLOY_ENV"
  set +a
fi

: "${PILOT_INGEST_PATH:=${ROOT}/data/pilot/kent_pilot_candidates.geojson}"
: "${PILOT_CONTAINER_PATH:=/app/data/pilot/kent_pilot_candidates.geojson}"
: "${PILOT_AUTO_PIPELINE:=0}"
: "${PILOT_MAX_PIPELINE:=500}"
: "${PUBLIC_API_URL:=https://api.vspecialist.com}"
: "${PHASE_A_API_BASE:=${PUBLIC_API_URL}}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL is required (deploy/.env)." >&2
  exit 2
fi

FETCH_ARGS=(-o "$PILOT_INGEST_PATH")
if [[ -n "${PILOT_FETCH_MAX_SCAN:-}" ]]; then
  FETCH_ARGS+=(--max-scan "$PILOT_FETCH_MAX_SCAN")
fi
if [[ -n "${PILOT_FETCH_MAX_KEPT:-}" ]]; then
  FETCH_ARGS+=(--max-kept "$PILOT_FETCH_MAX_KEPT")
fi
if [[ "${PILOT_STATS_ONLY:-0}" == "1" ]]; then
  FETCH_ARGS+=(--stats-only)
fi

echo "=== Pilot parcel funnel (WaTech → prescreen GeoJSON) ==="
"$PY" scripts/fetch_pilot_parcel_candidates.py "${FETCH_ARGS[@]}"

if [[ "${PILOT_STATS_ONLY:-0}" == "1" ]]; then
  echo "PILOT_STATS_ONLY=1 — done."
  exit 0
fi

if [[ ! -f "$PILOT_INGEST_PATH" ]]; then
  echo "error: expected output file $PILOT_INGEST_PATH" >&2
  exit 1
fi

if [[ "${PILOT_SKIP_INGEST:-0}" == "1" ]]; then
  echo "PILOT_SKIP_INGEST=1 — GeoJSON at $PILOT_INGEST_PATH"
  exit 0
fi

if [[ -z "${INTERNAL_API_KEY:-}" ]]; then
  echo "error: INTERNAL_API_KEY required for ingest POST." >&2
  exit 2
fi

API_BASE="${PHASE_A_API_BASE%/}"
CURL=(curl -sS -f)
if [[ "${PILOT_STRICT_TLS:-0}" != "1" ]] && [[ "$API_BASE" == https://* ]]; then
  CURL+=(-k)
fi

echo "=== Ingest GeoJSON (server path for worker mount) ==="
echo "Host file: $PILOT_INGEST_PATH"
echo "Container path: $PILOT_CONTAINER_PATH"

INGEST_JSON="$(
  "$PY" - <<PY
import json
print(json.dumps({
    "path": "${PILOT_CONTAINER_PATH}",
    "default_county_fips": "53033",
    "auto_run_pipeline": bool(int("${PILOT_AUTO_PIPELINE}")),
    "max_auto_pipeline": int("${PILOT_MAX_PIPELINE}"),
}))
PY
)"

"${CURL[@]}" -X POST "${API_BASE}/internal/ingest/geojson-server-path" \
  -H "X-Internal-Key: ${INTERNAL_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$INGEST_JSON" | "$PY" -m json.tool

echo ""
echo "=== Apply pilot scope tags (Kent + unincorporated) ==="
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env exec -T api \
  python3 /app/scripts/apply_pilot_scope.py

echo ""
echo "Done. Check operator console: ${PUBLIC_API_URL%/}/operator/parcels (via UI_HOST)"
