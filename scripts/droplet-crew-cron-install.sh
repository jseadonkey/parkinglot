#!/usr/bin/env bash
# Install weekly CrewAI tools preflight cron on the parkinglot Droplet (Mon 06:00 UTC).
# Run once: cd /opt/workspaces/parkinglot && ./scripts/droplet-crew-cron-install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "error: run on Droplet at /opt/workspaces/parkinglot" >&2
  exit 1
fi

chmod +x "${ROOT}/scripts/droplet-crew-smoke.sh"
LOG="${ROOT}/services/crew/output/cron.log"
mkdir -p "${ROOT}/services/crew/output"
CRON_LINE="0 6 * * 1 cd ${ROOT} && ${ROOT}/scripts/droplet-crew-smoke.sh >> ${LOG} 2>&1"

( crontab -l 2>/dev/null | grep -v 'droplet-crew-smoke.sh' || true
  echo "$CRON_LINE"
) | crontab -

echo "Installed cron (Mon 06:00 UTC): droplet-crew-smoke.sh"
echo "Log: ${LOG}"
