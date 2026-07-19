#!/usr/bin/env bash
# Rsync repo to the parkinglot Droplet only (validates deploy/droplet.target).
#   ./scripts/sync-to-droplet.sh
#   make droplet-sync
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/sync-to-droplet.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

# Guard: never clobber newer work that exists only on the Droplet.
# The Droplet auto-commits every 15 min; if its tree is dirty or ahead of the
# Mac's HEAD, a blind mirror sync would erase that work (this happened 2026-07-19).
LOCAL_HEAD="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo none)"
REMOTE_STATE="$(ssh "${SSH_USER}@${DROPLET}" \
  "cd '${REMOTE_PATH}' && git rev-parse HEAD 2>/dev/null; git status --porcelain 2>/dev/null | head -1" || true)"
REMOTE_HEAD="$(echo "$REMOTE_STATE" | head -1)"
REMOTE_DIRTY="$(echo "$REMOTE_STATE" | sed -n 2p)"
if [[ "${FORCE_DROPLET_SYNC:-}" != "1" ]]; then
  if [[ -n "$REMOTE_DIRTY" ]]; then
    echo "ABORT: Droplet working tree has uncommitted changes — syncing would destroy them." >&2
    echo "Wait for the Droplet auto-commit (runs every 15 min), pull, then retry." >&2
    echo "Override only if you are sure: FORCE_DROPLET_SYNC=1 make droplet-sync" >&2
    exit 1
  fi
  if [[ -n "$REMOTE_HEAD" && "$REMOTE_HEAD" != "$LOCAL_HEAD" ]] && \
     ! git -C "$ROOT" merge-base --is-ancestor "$REMOTE_HEAD" "$LOCAL_HEAD" 2>/dev/null; then
    echo "ABORT: Droplet is on commit ${REMOTE_HEAD:0:9} which this Mac clone does not contain." >&2
    echo "Pull the latest from origin/main first, then retry." >&2
    echo "Override only if you are sure: FORCE_DROPLET_SYNC=1 make droplet-sync" >&2
    exit 1
  fi
fi

echo "Syncing $ROOT -> ${SSH_USER}@${DROPLET}:${REMOTE_PATH}"
# Note: no --delete. Mirror-deleting removed Droplet-only work on 2026-07-19;
# stale files are cleaned up explicitly instead of by blind mirroring.
rsync -az \
  --exclude .git \
  --exclude node_modules \
  --exclude .venv \
  --exclude __pycache__ \
  --exclude .next \
  --exclude '*.pyc' \
  --exclude .env \
  --exclude deploy/.env \
  --exclude 'data/king/' \
  --exclude 'data/snohomish/' \
  --exclude 'data/kitsap/' \
  --exclude 'data/thurston/' \
  --exclude 'data/benton/' \
  --exclude 'data/pierce/' \
  --exclude 'data/wa/' \
  "$ROOT/" "${SSH_USER}@${DROPLET}:${REMOTE_PATH}/"
