#!/usr/bin/env bash
# Run on your LAPTOP from your local clone root (same layout as this repo).
# Syncs working tree to the DigitalOcean droplet. Does not delete remote-only files
# unless you pass --delete (see below).
set -euo pipefail

DROPLET_HOST="${DROPLET_HOST:-209.38.142.108}"
DROPLET_USER="${DROPLET_USER:-root}"
REMOTE_PATH="${REMOTE_PATH:-/opt/workspaces/parkinglot}"

RSYNC_DELETE=()
if [[ "${1:-}" == "--delete" ]]; then
  RSYNC_DELETE=(--delete)
  shift
fi

echo "Using ${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_PATH}"
echo "Local dir: $(pwd)"
echo "Tip: keep .env on the server — it is excluded. Use --delete only if you want exact mirror (removes remote files missing locally)."
sleep 1

rsync -avz --progress "${RSYNC_DELETE[@]}" \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '.ruff_cache/' \
  --exclude '.env' \
  --exclude 'node_modules/' \
  --exclude '.venv/' \
  ./ "${DROPLET_USER}@${DROPLET_HOST}:${REMOTE_PATH}/"

echo "Done. On droplet: sudo chown -R nobody:nogroup '${REMOTE_PATH}' && cd '${REMOTE_PATH}' && docker compose ps"
