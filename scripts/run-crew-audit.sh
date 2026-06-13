#!/usr/bin/env bash
# Run CrewAI tools preflight (no LLM). Uses repo .venv; loads deploy/.env when present.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "${ROOT}/.venv/bin/parking-crew" ]]; then
  chmod +x scripts/run-crew-tests.sh
  ./scripts/run-crew-tests.sh
fi

FIPS="${COUNTY_FIPS:-24510}"
EXTRA=()
if [[ "${1:-}" == "--quiet" ]] || [[ "${QUIET:-}" == "1" ]]; then
  EXTRA+=(-q)
fi

exec "${ROOT}/.venv/bin/parking-crew" tools-preflight --county-fips "$FIPS" "${EXTRA[@]}"
