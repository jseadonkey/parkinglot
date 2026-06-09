#!/usr/bin/env bash
# Operator agents help + install (address health Droplet cron; admin agent is GitHub Actions).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" == /opt/workspaces/parkinglot* ]]; then
  exec bash "${ROOT}/scripts/droplet-operator-agents-install.sh"
fi

cat <<EOF
Operator agents (see config/operator_agents.yaml):

  Push to main → Container images → Deploy to Droplet (automatic API rebuild)

  Address health (12h): .github/workflows/address-health-agent.yml
    + Celery Beat ADDRESS_HEALTH_AGENT_ENABLED on Droplet

  Operator admin (daily 08:00 UTC): .github/workflows/operator-admin-agent.yml
    Requires GitHub secrets: UI_SMOKE_ADMIN_EMAIL, UI_SMOKE_ADMIN_PASSWORD

On Droplet, run: ./scripts/droplet-operator-agents-install.sh
EOF
