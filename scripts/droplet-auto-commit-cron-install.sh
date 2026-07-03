#!/usr/bin/env bash
# Install periodic auto-commit cron on the parkinglot Droplet (every 15 minutes).
# Run once: cd /opt/workspaces/parkinglot && ./scripts/droplet-auto-commit-cron-install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "error: run on Droplet at /opt/workspaces/parkinglot" >&2
  exit 1
fi

chmod +x "${ROOT}/scripts/droplet-auto-commit.sh"
LOG="/var/log/parkinglot-auto-commit.log"
mkdir -p "${ROOT}/data/operator-agent"
CRON_LINE="*/15 * * * * cd ${ROOT} && ${ROOT}/scripts/droplet-auto-commit.sh >> ${LOG} 2>&1"

( crontab -l 2>/dev/null | grep -v 'droplet-auto-commit.sh' || true
  echo "$CRON_LINE"
) | crontab -

echo "Installed cron (every 15 min): droplet-auto-commit.sh"
echo "Log: ${LOG}"
