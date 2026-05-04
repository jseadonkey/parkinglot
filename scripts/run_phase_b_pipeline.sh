#!/usr/bin/env bash
# Build King/Kent zoning overlay from public layers + merge into parcels (Phase B end-to-end).
#
# Prerequisites (repo root on Droplet):
#   set -a && source deploy/.env && set +a
#   export DATABASE_URL INTERNAL_API_KEY
#   export KENT_ZONING='https://…/FeatureServer/0'
#   export KING_ZONING='https://…/FeatureServer/0'
#
# Optional:
#   OVERLAY_OUT — default data/zoning/wa/king_kent_zoning_overlay.geojson (host path)
#   PHASE_B_OVERLAY_PATH — path inside worker container (default /app/data/zoning/wa/…)
#   PHASE_B_* — same as scripts/execute-phase-b.sh (API base, max pipeline, etc.)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DEPLOY_ENV="${ROOT}/deploy/.env"
if [[ -f "$DEPLOY_ENV" ]] && { [[ -z "${DATABASE_URL:-}" ]] || [[ -z "${INTERNAL_API_KEY:-}" ]]; }; then
  set -a
  # shellcheck disable=SC1091
  source "$DEPLOY_ENV"
  set +a
fi

: "${OVERLAY_OUT:=${ROOT}/data/zoning/wa/king_kent_zoning_overlay.geojson}"
: "${PHASE_B_OVERLAY_PATH:=/app/data/zoning/wa/king_kent_zoning_overlay.geojson}"

if [[ -z "${KENT_ZONING:-}" || -z "${KING_ZONING:-}" ]]; then
  echo "error: set KENT_ZONING and KING_ZONING (Feature Layer URLs or paths to GeoJSON)." >&2
  echo "See docs/zoning-sources-kent.md and docs/PROCESS-COVERAGE.md" >&2
  exit 2
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL is required." >&2
  exit 2
fi

echo "=== build overlay -> ${OVERLAY_OUT} ==="
python3 "${ROOT}/scripts/build_king_kent_zoning_overlay.py" -o "${OVERLAY_OUT}"

echo "=== validate overlay ==="
python3 "${ROOT}/scripts/validate_phase_b_overlay.py" "${OVERLAY_OUT}"

CONTAINER_OUT="${PHASE_B_OVERLAY_PATH}"
HOST_VALIDATE="${OVERLAY_OUT}"
export PHASE_B_OVERLAY_PATH="${CONTAINER_OUT}"
export PHASE_B_OVERLAY_VALIDATE_PATH="${HOST_VALIDATE}"

echo "=== merge (execute-phase-b.sh) worker path=${CONTAINER_OUT} ==="
chmod +x "${ROOT}/scripts/execute-phase-b.sh"
"${ROOT}/scripts/execute-phase-b.sh"

echo "=== Phase B pipeline finished ==="
