#!/usr/bin/env bash
# Phase C — export readiness (owner outreach gaps) + smoke portfolio internal APIs.
#
# Requires:
#   DATABASE_URL — same Postgres URL as the API (for CLI gap counts)
#
# Optional HTTP (portfolio rollup — same auth as other /internal/*):
#   PHASE_C_API_BASE       — default http://127.0.0.1:8000
#   INTERNAL_API_KEY       — X-Internal-Key when API enforces it
#   PHASE_C_SKIP_HTTP=1    — only run check_export_readiness.py
#   PHASE_C_OWNER_KEY      — if set, GET /internal/owners/peers-by-key for this normalized_owner_key
#   PHASE_C_MIN_PEERS      — default 2 — portfolios-ranked query
#   PHASE_C_PORTFOLIOS_LIMIT — default 20 — portfolios-ranked limit
#
# Droplet (API only reachable inside container or via PUBLIC_API_URL):
#   docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env exec -T api bash -lc \
#     'export DATABASE_URL INTERNAL_API_KEY PHASE_C_API_BASE=http://127.0.0.1:8000
#       /app/scripts/execute-phase-c.sh'
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${PHASE_C_API_BASE:=http://127.0.0.1:8000}"
: "${PHASE_C_SKIP_HTTP:=0}"
: "${PHASE_C_MIN_PEERS:=2}"
: "${PHASE_C_PORTFOLIOS_LIMIT:=20}"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL is not set (same URL the API uses)." >&2
  exit 2
fi

echo "=== Phase C — export readiness (check parcels_missing_owner_outreach_brief) ==="
"$PY" "${ROOT}/scripts/check_export_readiness.py"
echo

if [[ "$PHASE_C_SKIP_HTTP" == "1" ]]; then
  echo "PHASE_C_SKIP_HTTP=1 — skipping portfolio HTTP smoke."
  exit 0
fi

KEY_HEADER=()
if [[ -n "${INTERNAL_API_KEY:-}" ]]; then
  KEY_HEADER=(-H "X-Internal-Key: ${INTERNAL_API_KEY}")
else
  echo "warning: INTERNAL_API_KEY unset — if production enforces it, curls may return 403." >&2
fi

BASE="${PHASE_C_API_BASE%/}"

PF_URL="${BASE}/internal/owners/portfolios-ranked?min_peers=${PHASE_C_MIN_PEERS}&limit=${PHASE_C_PORTFOLIOS_LIMIT}"
echo "=== GET ${PF_URL} ==="
curl -sS "${KEY_HEADER[@]}" "$PF_URL" -H "Accept: application/json" | "${PY}" -m json.tool 2>/dev/null || curl -sS "${KEY_HEADER[@]}" "$PF_URL" -H "Accept: application/json"
echo
echo

if [[ -n "${PHASE_C_OWNER_KEY:-}" ]]; then
  echo "=== GET /internal/owners/peers-by-key (normalized_owner_key) ==="
  curl -sS "${KEY_HEADER[@]}" -G "${BASE}/internal/owners/peers-by-key" \
    --data-urlencode "normalized_owner_key=${PHASE_C_OWNER_KEY}" \
    -H "Accept: application/json" | "${PY}" -m json.tool 2>/dev/null || \
    curl -sS "${KEY_HEADER[@]}" -G "${BASE}/internal/owners/peers-by-key" \
      --data-urlencode "normalized_owner_key=${PHASE_C_OWNER_KEY}" \
      -H "Accept: application/json"
  echo
  echo
fi

echo "Phase C script complete."
echo "Reduce parcels_missing_owner_outreach_brief via pipeline completion or parcel outreach recompute."
