#!/usr/bin/env bash
# One-time: install parking-crew on the Droplet. Run from /opt/workspaces/parkinglot.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
chmod +x scripts/droplet-crew-env-sync.sh scripts/droplet-crew-langfuse-setup.sh 2>/dev/null || true
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
( cd "${ROOT}/services/crew" && "${ROOT}/.venv/bin/pip" install -q ".[observability]" )
./scripts/droplet-crew-env-sync.sh
echo "Installed. Run: .venv/bin/parking-crew secrets-status"
