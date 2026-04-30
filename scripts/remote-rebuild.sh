#!/usr/bin/env bash
# SSH to Droplet and rebuild/restart the production stack.
# Requires deploy/.env already on the server. Example:
#   DROPLET=203.0.113.10 REMOTE_PATH=/opt/parking-acquisition-agents ./scripts/remote-rebuild.sh
set -euo pipefail

: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
REMOTE_PATH="${REMOTE_PATH:-/opt/parking-acquisition-agents}"
SSH_USER="${SSH_USER:-root}"

ssh "${SSH_USER}@${DROPLET}" bash -s <<EOF
set -euo pipefail
cd "${REMOTE_PATH}"
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env ps
EOF
