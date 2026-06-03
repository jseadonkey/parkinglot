#!/usr/bin/env bash
# One Celery POI batch at a time (Overpass only works from worker containers).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
POI_LIMIT="${POI_LIMIT:-50}"
COUNTY="${COUNTY:-24510}"
LOG="${LOG:-/tmp/baltimore-poi-refresh.log}"

PUBLIC_API_URL=$(grep '^PUBLIC_API_URL=' deploy/.env | cut -d= -f2-)
INTERNAL_API_KEY=$(grep '^INTERNAL_API_KEY=' deploy/.env | cut -d= -f2-)
BASE="${PUBLIC_API_URL%/}"

exec >>"$LOG" 2>&1
echo "=== POI Celery loop $(date -Is) limit=$POI_LIMIT ==="

while true; do
  missing=$(docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env exec -T api python - <<'PY' 2>/dev/null || echo 1
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.db.models import Parcel
db = SessionLocal()
try:
    n = db.scalar(select(func.count()).select_from(Parcel).where(
        Parcel.county_fips == "24510", Parcel.poi_commercial_count_400m.is_(None), Parcel.footprint.isnot(None)
    ))
    print(n or 0)
finally:
    db.close()
PY
)
  if [[ "${missing:-1}" -eq 0 ]]; then
    echo "=== complete $(date -Is) ==="
    exit 0
  fi
  echo "--- batch $(date -Is) missing=$missing ---"
  resp=$(curl -sSk -X POST "${BASE}/internal/metrics/refresh-poi-density?limit=${POI_LIMIT}&county_fips=${COUNTY}&only_missing=true" \
    -H "Content-Type: application/json" -H "X-Internal-Key: ${INTERNAL_API_KEY}" -d '{}')
  tid=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || true)
  if [[ -z "$tid" ]]; then
    echo "no task_id: $resp"
    sleep 60
    continue
  fi
  # ~1 sec/parcel; wait up to 15 min per batch before next POST (avoid overlapping tasks).
  for _ in $(seq 1 180); do
    active=$(docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env exec -T worker \
      celery -A app.celery_app inspect active 2>/dev/null | grep -c refresh_poi_density_batch || true)
    st=$(curl -sSk "${BASE}/internal/tasks/${tid}" -H "X-Internal-Key: ${INTERNAL_API_KEY}")
    ready=$(echo "$st" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ready',False))" 2>/dev/null || echo False)
    if [[ "$ready" == "True" ]]; then
      echo "$st" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state'), d.get('result') or d.get('error'))"
      break
    fi
    if [[ "${active:-0}" -eq 0 ]]; then
      sleep 5
      st=$(curl -sSk "${BASE}/internal/tasks/${tid}" -H "X-Internal-Key: ${INTERNAL_API_KEY}")
      ready=$(echo "$st" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ready',False))" 2>/dev/null || echo False)
      if [[ "$ready" == "True" ]]; then
        echo "$st" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state'), d.get('result') or d.get('error'))"
        break
      fi
    fi
    sleep 5
  done
  sleep 3
done
