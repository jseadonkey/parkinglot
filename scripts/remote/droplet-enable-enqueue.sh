#!/usr/bin/env bash
# Re-enable periodic incomplete-pipeline enqueue (after relieve-load).
#
# Run on Droplet from repo root:
#   ENQUEUE_LIMIT=50 COMPOSE_FILE=deploy/docker-compose.production.ghcr.yml bash scripts/remote/droplet-enable-enqueue.sh
set -euo pipefail

if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "-" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
else
  ROOT="$(pwd)"
fi
cd "$ROOT"
test -f deploy/.env

COMPOSE_REL="${COMPOSE_FILE:-deploy/docker-compose.production.ghcr.yml}"
export ENQUEUE_LIMIT="${ENQUEUE_LIMIT:-50}"

exec bash .github/workflows/scripts/droplet-remote-checks.sh enable-enqueue "$COMPOSE_REL"
