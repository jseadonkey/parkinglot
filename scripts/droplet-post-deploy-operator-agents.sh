#!/usr/bin/env bash
# Post-deploy: verify new API routes/metrics are live, install operator-agent Droplet crons.
# Called from GitHub Actions deploy-droplet.yml over SSH (and safe to re-run manually on the Droplet).
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

echo "==> operator agents post-deploy (compose=${COMPOSE_FILE})"

echo "==> install Droplet crons (address health backup)"
bash "${ROOT}/scripts/droplet-operator-agents-install.sh"

echo "==> verify WA centroid backfill route in running API container"
docker compose -f "$COMPOSE_FILE" $PG_EXTRA --env-file deploy/.env exec -T api python - <<'PY'
from app.main import app

paths = {getattr(r, "path", "") for r in app.routes}
needed = "/internal/metrics/backfill-wa-centroid-addresses"
if needed not in paths:
    raise SystemExit(
        f"missing route {needed!r} — push to main, wait for Container images + Deploy to Droplet, "
        "or rebuild api with docker compose up --force-recreate api worker beat"
    )
print(f"OK route: {needed}")
PY

echo "==> verify backlog metric wa_property_addresses in API image"
docker compose -f "$COMPOSE_FILE" $PG_EXTRA --env-file deploy/.env exec -T api python - <<'PY'
import inspect

import app.backlog_eta as backlog_eta

src = inspect.getsource(backlog_eta.backlog_eta_summary)
if "wa_property_addresses" not in src:
    raise SystemExit("backlog_eta missing wa_property_addresses row — API image is stale")
print("OK backlog metric: wa_property_addresses")
PY

echo "==> operator agents post-deploy complete"
