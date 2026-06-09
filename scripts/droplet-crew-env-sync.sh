#!/usr/bin/env bash
# Run ON the parkinglot Droplet only. Merges deploy/.env → services/crew/.env (no Mac, no SSH).
#   cd /opt/workspaces/parkinglot && ./scripts/droplet-crew-env-sync.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "error: run this on the Droplet at /opt/workspaces/parkinglot (not on Mac clone)." >&2
  exit 1
fi

test -f deploy/.env || { echo "error: deploy/.env missing" >&2; exit 1; }

export ON_DROPLET=1
exec "${ROOT}/scripts/sync-crew-secrets.sh" --on-droplet "$@"
