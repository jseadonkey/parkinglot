#!/usr/bin/env bash
# Run Phase B build+merge for one WA county on a dedicated worker container (bypasses parking queue).
# Usage: ./scripts/droplet-phase-b-run-county.sh 53061 [max_pipeline]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "error: run on parkinglot Droplet at /opt/workspaces/parkinglot" >&2
  exit 1
fi

FIPS="${1:-}"
MAX_PIPE="${2:-50}"
if [[ ! "$FIPS" =~ ^530[0-9]{2}$ ]]; then
  echo "usage: $0 <county_fips> [max_pipeline]" >&2
  exit 1
fi

NAME="phase-b-${FIPS}"
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  state="$(docker inspect "$NAME" --format '{{.State.Status}}')"
  if [[ "$state" == "running" ]]; then
    echo "already running: $NAME"
    exit 0
  fi
  docker rm "$NAME" >/dev/null
fi

COMPOSE=(docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env)

"${COMPOSE[@]}" run -d --no-deps --name "$NAME" worker python -c "
from app.tasks import fetch_build_merge_wa_county_zoning
import json
out = fetch_build_merge_wa_county_zoning.run('${FIPS}', max_pipeline=${MAX_PIPE})
print(json.dumps(out, default=str))
"

echo "started $NAME (county ${FIPS}, max_pipeline=${MAX_PIPE})"
echo "logs: docker logs -f $NAME"
