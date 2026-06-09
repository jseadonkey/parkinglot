#!/usr/bin/env bash
# Production smoke: Langfuse auth + DB tools preflight on the Droplet.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FIPS="${COUNTY_FIPS:-24510}"

echo "==> Langfuse (US hardwired)"
.venv/bin/parking-crew langfuse-check

echo "==> Tools preflight FIPS=${FIPS}"
.venv/bin/parking-crew tools-preflight --county-fips "$FIPS" -q

echo "==> Done. Reports in services/crew/output/"
