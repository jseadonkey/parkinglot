#!/usr/bin/env bash
# Print Alembic heads (run from repo root or services/api).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/services/api"
if [[ -x "${ROOT}/.venv/bin/alembic" ]]; then
  exec "${ROOT}/.venv/bin/alembic" heads "$@"
fi
exec alembic heads "$@"
