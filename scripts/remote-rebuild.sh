#!/usr/bin/env bash
# SSH to Droplet and rebuild/restart the production stack.
# Requires deploy/.env already on the server. Example:
#   DROPLET=203.0.113.10 REMOTE_PATH=/opt/parking-acquisition-agents ./scripts/remote-rebuild.sh
#
# Optional: bundle on-Droplet PostGIS (see deploy/docker-compose.postgis-addon.yml):
#   USE_LOCAL_POSTGIS=1 DROPLET=... ./scripts/remote-rebuild.sh
set -euo pipefail

: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
REMOTE_PATH="${REMOTE_PATH:-/opt/parking-acquisition-agents}"
SSH_USER="${SSH_USER:-root}"
USE_LOCAL_POSTGIS="${USE_LOCAL_POSTGIS:-0}"

ssh "${SSH_USER}@${DROPLET}" \
  "env REMOTE_PATH=$(printf '%q' "$REMOTE_PATH") USE_LOCAL_POSTGIS=$(printf '%q' "$USE_LOCAL_POSTGIS") bash -s" <<'EOS'
set -euo pipefail
cd "$REMOTE_PATH"
PRIMARY="deploy/docker-compose.production.yml"
if [ "${USE_LOCAL_POSTGIS}" = "1" ]; then
  ARGS=(-f "$PRIMARY" -f deploy/docker-compose.postgis-addon.yml --env-file deploy/.env)
else
  ARGS=(-f "$PRIMARY" --env-file deploy/.env)
fi
docker compose "${ARGS[@]}" up -d --build
docker compose "${ARGS[@]}" ps
EOS
