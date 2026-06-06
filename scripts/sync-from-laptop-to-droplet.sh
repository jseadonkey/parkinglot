#!/usr/bin/env bash
# Run on your LAPTOP from your local clone root (same layout as this repo).
# Syncs working tree to the locked parkinglot Droplet target. Does not delete
# remote-only files unless you pass --delete (see below).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"

# Backward-compatible env names for older laptop notes.
DROPLET="${DROPLET:-${DROPLET_HOST:-}}"
SSH_USER="${SSH_USER:-${DROPLET_USER:-}}"
assert_droplet_target "$ROOT/scripts/sync-from-laptop-to-droplet.sh" "$DROPLET" "${REMOTE_PATH:-}" "$SSH_USER" || exit 1

RSYNC_DELETE=()
if [[ "${1:-}" == "--delete" ]]; then
  RSYNC_DELETE=(--delete)
  shift
fi

echo "Using ${SSH_USER}@${DROPLET}:${REMOTE_PATH}"
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
  ./ "${SSH_USER}@${DROPLET}:${REMOTE_PATH}/"

echo "Done. On droplet: sudo chown -R nobody:nogroup '${REMOTE_PATH}' && cd '${REMOTE_PATH}' && docker compose ps"
