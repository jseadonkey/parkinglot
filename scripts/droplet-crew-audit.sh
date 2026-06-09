#!/usr/bin/env bash
# Run crew tools-preflight ON the Droplet (production DB + Slack). No Mac required.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FIPS="${COUNTY_FIPS:-24510}"
test -x scripts/droplet-crew-install.sh && ./scripts/droplet-crew-install.sh >/dev/null 2>&1 || ./scripts/droplet-crew-install.sh
exec .venv/bin/parking-crew tools-preflight --county-fips "$FIPS" "$@"
