#!/usr/bin/env bash
# Install workspace packages into .venv (first run) and run the sample parking trace tests.
# Same packages as CI (.github/workflows/ci.yml "Install workspace packages").
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="${ROOT}/.venv"
PY="${VENV}/bin/python"
if [[ ! -x "$PY" ]]; then
  python3 -m venv "${VENV}"
  PY="${VENV}/bin/python"
  "${PY}" -m pip install --upgrade pip
  "${PY}" -m pip install ./packages/core ./services/scoring ./services/ingestion ./services/enrichment ./services/workflows "./services/api[dev]"
fi
exec "${PY}" -m pytest "${ROOT}/services/api/tests/test_sample_parking_trace.py" -v --tb=short "$@"
