#!/usr/bin/env bash
# Rsync repo to a DigitalOcean Droplet (from your laptop). Example:
#   DROPLET=203.0.113.10 ./scripts/sync-to-droplet.sh
# Override path if needed:
#   DROPLET=203.0.113.10 REMOTE_PATH=/opt/parking-acquisition-agents ./scripts/sync-to-droplet.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
REMOTE_PATH="${REMOTE_PATH:-/opt/parking-acquisition-agents}"
SSH_USER="${SSH_USER:-root}"

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
