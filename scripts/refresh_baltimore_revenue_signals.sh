#!/usr/bin/env bash
# Baltimore City: seed paid parking rate comps + refresh demand distances + OSM POI density.
# Run on the production Droplet from repo root (needs deploy/.env with INTERNAL_API_KEY).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE="${COMPOSE:-deploy/docker-compose.production.ghcr.yml}"
POI_LIMIT="${POI_LIMIT:-50}"
DEMAND_LIMIT="${DEMAND_LIMIT:-2000}"
COUNTY="${COUNTY:-24510}"

if [[ -f deploy/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source deploy/.env
  set +a
fi

BASE="${PUBLIC_API_URL:-http://127.0.0.1:8000}"
BASE="${BASE%/}"
KEY="${INTERNAL_API_KEY:-}"

echo "==> Alembic upgrade (parking_rate_comps + poi_commercial_count_400m)"
docker compose -f "$COMPOSE" --env-file deploy/.env exec -T api alembic upgrade heads

echo "==> Seed Baltimore rate comps"
docker compose -f "$COMPOSE" --env-file deploy/.env exec -T api python - <<'PY'
from app.db.session import SessionLocal
from app.rate_comp_seed import seed_baltimore_parking_rate_comps

db = SessionLocal()
try:
    print(seed_baltimore_parking_rate_comps(db))
finally:
    db.close()
PY

_post() {
  local path="$1"
  if [[ -z "$KEY" ]]; then
    echo "SKIP (no INTERNAL_API_KEY): POST $path"
    return 0
  fi
  curl -sSk -X POST "${BASE}${path}" \
    -H "Content-Type: application/json" \
    -H "X-Internal-Key: $KEY" \
    -d '{}'
  echo ""
}

echo "==> Refresh demand distances (county $COUNTY, tier A+B generators, all parcels)"
_post "/internal/metrics/refresh-demand-distances?limit=${DEMAND_LIMIT}&county_fips=${COUNTY}&process_all=true"

echo "==> Rescore entitlement (county $COUNTY, all parcels)"
_post "/internal/metrics/refresh-entitlement-scores?limit=${DEMAND_LIMIT}&county_fips=${COUNTY}&process_all=true"

echo "==> Refresh OSM POI density (county $COUNTY, limit $POI_LIMIT — ~1 req/sec)"
_post "/internal/metrics/refresh-poi-density?limit=${POI_LIMIT}&county_fips=${COUNTY}&only_missing=true"

echo "==> Done. Poll Celery tasks with GET /internal/tasks/{task_id}"
echo "    Re-run with POI_LIMIT=50 until export-readiness shows no missing POI counts."
