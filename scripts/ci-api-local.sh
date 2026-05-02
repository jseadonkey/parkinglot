#!/usr/bin/env bash
# Mirror .github/workflows/ci.yml jobs ``lint`` + ``test-api`` (Ruff + pytest + OpenAPI export smoke, no Docker).
# Creates ``.venv`` at repo root on first run; requires network for pip until deps are installed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip -q
pip install ruff==0.9.7 -q
pip install ./packages/core ./services/scoring ./services/ingestion ./services/enrichment ./services/workflows "./services/api[dev]" -q
ruff check packages/core services/api/app services/scoring services/ingestion services/enrichment services/workflows services/api/tests scripts
(
  cd services/api
  pytest "$@"
)
python3 scripts/export_openapi_json.py --indent 0 | python3 -m json.tool > /dev/null
