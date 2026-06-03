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
}

_task_id() {
  python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || true
}

_wait_task() {
  local tid="$1"
  local label="$2"
  if [[ -z "$tid" || -z "$KEY" ]]; then
    return 0
  fi
  echo "    Waiting for $label (task $tid)..."
  for _ in $(seq 1 360); do
    local st ready
    st=$(curl -sSk "${BASE}/internal/tasks/${tid}" -H "X-Internal-Key: $KEY")
    ready=$(echo "$st" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ready',False))" 2>/dev/null || echo False)
    if [[ "$ready" == "True" ]]; then
      echo "$st" | python3 -c "import sys,json; d=json.load(sys.stdin); print('    ', d.get('state'), d.get('result') or d.get('error'))"
      return 0
    fi
    sleep 5
  done
  echo "    WARN: timed out waiting for $label"
}

echo "==> Refresh demand distances (county $COUNTY, all parcels)"
DEMAND_TID=$(_post "/internal/metrics/refresh-demand-distances?limit=${DEMAND_LIMIT}&county_fips=${COUNTY}&process_all=true" | _task_id)
echo "{\"task_id\":\"${DEMAND_TID}\"}"
_wait_task "$DEMAND_TID" "demand distances"

echo "==> Rescore entitlement (county $COUNTY, all parcels)"
ENT_TID=$(_post "/internal/metrics/refresh-entitlement-scores?limit=${DEMAND_LIMIT}&county_fips=${COUNTY}&process_all=true" | _task_id)
echo "{\"task_id\":\"${ENT_TID}\"}"
_wait_task "$ENT_TID" "entitlement scores"

echo "==> POI density: start background loop (one Celery batch at a time; needs worker Overpass)"
echo "    nohup bash scripts/refresh_baltimore_poi_loop.sh </dev/null >/dev/null 2>&1 &"
echo "    tail -f /tmp/baltimore-poi-refresh.log"
if [[ -n "$KEY" ]] && [[ "${START_POI_LOOP:-}" == "1" ]]; then
  nohup bash "$ROOT/scripts/refresh_baltimore_poi_loop.sh" </dev/null >/dev/null 2>&1 &
  echo "    Started POI loop (pid $!)."
fi

echo "==> Done (comps + demand + entitlement). POI fills via refresh_baltimore_poi_loop.sh."
