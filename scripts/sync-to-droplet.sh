#!/usr/bin/env bash
# Rsync repo to the parkinglot Droplet only (validates deploy/droplet.target).
#   ./scripts/sync-to-droplet.sh
#   make droplet-sync
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/sync-to-droplet.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

echo "Syncing $ROOT -> ${SSH_USER}@${DROPLET}:${REMOTE_PATH}"
rsync -az --delete \
  --exclude .git \
  --exclude node_modules \
  --exclude .venv \
  --exclude __pycache__ \
  --exclude .next \
  --exclude '*.pyc' \
  --exclude .env \
  --exclude deploy/.env \
  "$ROOT/" "${SSH_USER}@${DROPLET}:${REMOTE_PATH}/"
