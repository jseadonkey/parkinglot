#!/usr/bin/env bash
# Run Ruff + pytest for the API stack (Python 3.12 via uv). Repo root: parkinglot/
#
#   ./scripts/run-api-tests.sh
#
# One-time: installs uv into .uv-bin/ and a venv into .venv/ (both gitignored).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UV="${ROOT}/.uv-bin/uv"
if [[ ! -x "$UV" ]]; then
  echo "Installing uv to ${ROOT}/.uv-bin ..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="${ROOT}/.uv-bin" INSTALLER_NO_MODIFY_PATH=1 sh
fi
"$UV" python install 3.12 >/dev/null
if [[ ! -x "${ROOT}/.venv/bin/python" ]]; then
  "$UV" venv --python 3.12 "${ROOT}/.venv"
fi
"$UV" pip install -p "${ROOT}/.venv/bin/python" --upgrade pip >/dev/null
"$UV" pip install -p "${ROOT}/.venv/bin/python" \
  ./packages/core \
  ./services/scoring \
  ./services/ingestion \
  ./services/enrichment \
  ./services/workflows \
  "./services/api[dev]" \
  ruff==0.9.7 >/dev/null

echo "==> ruff" >&2
"${ROOT}/.venv/bin/ruff" check \
  packages/core \
  services/api/app \
  services/scoring \
  services/ingestion \
  services/enrichment \
  services/workflows \
  services/api/tests

echo "==> pytest" >&2
"${ROOT}/.venv/bin/python" -m pytest "${ROOT}/services/api/tests" -q
echo "OK" >&2
