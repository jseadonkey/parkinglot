#!/usr/bin/env bash
# Run the 12h address health agent inside the worker container (SQLAlchemy + DATABASE_URL).
# Used by GitHub Actions, Droplet cron, and Celery Beat subprocess.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.production.ghcr.yml}"
PG_EXTRA=""
if [[ "${USE_LOCAL_POSTGIS:-}" == "1" || "${USE_LOCAL_POSTGIS:-}" == "true" ]]; then
  PG_EXTRA="-f deploy/docker-compose.postgis-addon.yml"
fi

test -f deploy/.env
mkdir -p "${ROOT}/data/operator-agent"

docker compose -f "$COMPOSE_FILE" $PG_EXTRA --env-file deploy/.env exec -T worker \
  python /app/scripts/address-health-agent/address_health_agent.py "$@"
