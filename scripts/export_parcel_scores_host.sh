#!/usr/bin/env bash
# Export scored parcels CSV to the host filesystem (not container /tmp).
#
# Run from repo root on the Droplet (or anywhere docker compose reaches the stack):
#   set -a && source deploy/.env && set +a
#   ./scripts/export_parcel_scores_host.sh
#
# Optional:
#   COMPOSE_FILE      — default deploy/docker-compose.production.yml
#   ENV_FILE          — default deploy/.env
#   EXPORT_OUT        — default ./parcel_scores_export.csv (repo root)
#   EXPORT_LIMIT      — if set, passes --limit to the exporter
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${COMPOSE_FILE:=deploy/docker-compose.production.yml}"
: "${ENV_FILE:=deploy/.env}"
: "${EXPORT_OUT:=${ROOT}/parcel_scores_export.csv}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found" >&2
  exit 2
fi

ARGS=(python /app/scripts/export_scored_parcels_csv.py -o -)
if [[ -n "${EXPORT_LIMIT:-}" ]]; then
  ARGS+=(--limit "$EXPORT_LIMIT")
fi

echo "Writing ${EXPORT_OUT} …"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T api "${ARGS[@]}" >"$EXPORT_OUT"
wc -l "$EXPORT_OUT"
echo "Done."
