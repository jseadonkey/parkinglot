#!/usr/bin/env bash
# Install hourly auto-commit + deploy cron on the parkinglot Droplet.
# Run once: cd /opt/workspaces/parkinglot && ./scripts/droplet-auto-commit-deploy-install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "error: run on Droplet at /opt/workspaces/parkinglot" >&2
  exit 1
fi

chmod +x "${ROOT}/scripts/droplet-auto-commit-deploy.sh"
mkdir -p "${ROOT}/ops"

if [[ -f deploy/.env ]] && ! grep -q '^AUTO_COMMIT_DEPLOY_ENABLED=' deploy/.env 2>/dev/null; then
  printf '\n# Hourly: commit safe uncommitted work and rebuild production (see scripts/droplet-auto-commit-deploy.sh)\nAUTO_COMMIT_DEPLOY_ENABLED=true\n' >>deploy/.env
  echo "Appended AUTO_COMMIT_DEPLOY_ENABLED=true to deploy/.env"
fi

LOG="${ROOT}/ops/auto-commit-deploy.log"
CRON_LINE="5 * * * * cd ${ROOT} && ${ROOT}/scripts/droplet-auto-commit-deploy.sh"

( crontab -l 2>/dev/null | grep -v 'droplet-auto-commit-deploy.sh' || true
  echo "$CRON_LINE"
) | crontab -

echo "Installed cron (every hour at :05 UTC): droplet-auto-commit-deploy.sh"
echo "Log: ${LOG}"
echo "Toggle: AUTO_COMMIT_DEPLOY_ENABLED=false in deploy/.env"
