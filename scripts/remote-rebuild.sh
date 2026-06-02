#!/usr/bin/env bash
# SSH to Droplet and rebuild/restart the production stack (validates deploy/droplet.target).
#   ./scripts/remote-rebuild.sh
#
# Optional: USE_LOCAL_POSTGIS=1 ./scripts/remote-rebuild.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/remote-rebuild.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

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
