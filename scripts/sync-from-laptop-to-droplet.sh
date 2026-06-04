#!/usr/bin/env bash
# Run on your LAPTOP from your local clone root (same layout as this repo).
# Syncs working tree to the parkinglot DigitalOcean Droplet only. Does not delete
# remote-only files unless you pass --delete (see below).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/sync-from-laptop-to-droplet.sh" "${DROPLET:-${DROPLET_HOST:-}}" "${REMOTE_PATH:-}" "${SSH_USER:-${DROPLET_USER:-}}" || exit 1

DROPLET_HOST="$DROPLET"
DROPLET_USER="$SSH_USER"

RSYNC_DELETE=()
if [[ "${1:-}" == "--delete" ]]; then
  RSYNC_DELETE=(--delete)
  shift
fi

echo "Using ${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_PATH}"
echo "Local dir: $ROOT"
echo "Tip: keep .env on the server — it is excluded. Use --delete only if you want exact mirror (removes remote files missing locally)."
sleep 1

rsync -avz --progress "${RSYNC_DELETE[@]}" \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '.ruff_cache/' \
  --exclude '.env' \
  --exclude 'node_modules/' \
  --exclude '.venv/' \
  "$ROOT/" "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_PATH}/"

echo "Done. On droplet: sudo chown -R nobody:nogroup '${REMOTE_PATH}' && cd '${REMOTE_PATH}' && docker compose ps"
