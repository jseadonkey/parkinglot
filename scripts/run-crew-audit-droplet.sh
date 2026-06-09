#!/usr/bin/env bash
# Run crew tools-preflight on the parkinglot Droplet (SSH alias from deploy/droplet.target).
# Does not require OPENAI_API_KEY — exercises DB + log commands when deploy/.env exists.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "${ROOT}/scripts/lib/droplet-target.sh"
assert_droplet_target "${ROOT}/scripts/run-crew-audit-droplet.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

FIPS="${COUNTY_FIPS:-24510}"

ssh -o BatchMode=yes -o ConnectTimeout=30 "${SSH_USER}@${DROPLET}" bash -s <<EOF
set -euo pipefail
cd "${REMOTE_PATH}"
if [[ ! -x .venv/bin/parking-crew ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q ./services/crew
fi
export FINOPS_SSH_HOST=
export FINOPS_LOG_COMMAND="docker compose -f deploy/docker-compose.production.yml logs --since 24h api worker beat 2>&1 | tail -n 200"
.venv/bin/parking-crew tools-preflight --county-fips "${FIPS}" -q
EOF
