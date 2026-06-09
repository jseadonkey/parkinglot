#!/usr/bin/env bash
# Fail if production-critical paths are missing from the current tree.
# Run in CI and before `make droplet-rebuild` so deploys cannot drop merged features.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

missing=0
require() {
  if [[ ! -e "$1" ]]; then
    echo "MISSING required path: $1" >&2
    missing=1
  fi
}

# Operator console
require apps/operator-console/app/backlog/page.tsx
require apps/operator-console/components/BacklogEtaPanel.tsx

# API modules
require services/api/app/backlog_eta.py
require services/api/app/ops_remediation.py
require services/api/app/poi_density.py
require services/api/app/baltimore_address_backfill.py
require services/api/app/load_governor.py

# Migrations (API crash-loops without these)
require services/api/alembic/versions/20260603_0010_poi_commercial_count.py
require services/api/alembic/versions/20260606_0011_production_stamp_compat.py
require services/api/alembic/versions/20260607_0010_parcel_scores_latest_index.py

# Internal routes wired in OpenAPI smoke
grep -q 'stats/backlog-eta' services/api/app/routers/internal.py || {
  echo "MISSING route: GET /internal/stats/backlog-eta" >&2
  missing=1
}
grep -q 'stats/load-governor' services/api/app/routers/internal.py || {
  echo "MISSING route: GET /internal/stats/load-governor" >&2
  missing=1
}
grep -q 'ops/run-now' services/api/app/routers/internal.py || {
  echo "MISSING route: POST /internal/ops/run-now" >&2
  missing=1
}

if [[ "$missing" -ne 0 ]]; then
  echo "Mainline parity check failed. Merge feature work to main before deploying." >&2
  exit 1
fi

echo "OK: mainline parity ($(git rev-parse --short HEAD))"
