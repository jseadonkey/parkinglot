# shellcheck shell=bash
# Source from other scripts/remote/*.sh after cd to repo root.
# Sets ARGS array for docker compose (production + optional postgis addon).
set -euo pipefail

COMPOSE_REL="${COMPOSE_REL:-deploy/docker-compose.production.yml}"
ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)
if grep -q '^POSTGRES_PASSWORD=' deploy/.env 2>/dev/null; then
  ARGS=(-f "$COMPOSE_REL" -f deploy/docker-compose.postgis-addon.yml --env-file deploy/.env)
  echo "(using postgis addon compose file — POSTGRES_PASSWORD is set)"
fi
