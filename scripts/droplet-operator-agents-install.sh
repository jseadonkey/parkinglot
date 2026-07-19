#!/usr/bin/env bash
# Install operator-agent crons on the parkinglot Droplet (address health backup; GHA is primary for browser agent).
# Invoked automatically from deploy-droplet.yml via droplet-post-deploy-operator-agents.sh.
# Manual: cd /opt/workspaces/parkinglot && ./scripts/droplet-operator-agents-install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "error: run on Droplet at /opt/workspaces/parkinglot" >&2
  exit 1
fi

mkdir -p "${ROOT}/data/operator-agent"
chmod +x "${ROOT}/scripts/address-health-agent/address_health_agent.py" 2>/dev/null || true
chmod +x "${ROOT}/scripts/run-address-health-agent-droplet.sh" 2>/dev/null || true
chmod +x "${ROOT}/scripts/operator-admin-agent/droplet-remediate.py" 2>/dev/null || true

LOG="${ROOT}/data/operator-agent/address-health-cron.log"
# Backup to Celery Beat + GitHub Actions (every 12h at :10 UTC).
CRON_LINE="10 */12 * * * cd ${ROOT} && bash scripts/run-address-health-agent-droplet.sh --json >> ${LOG} 2>&1"

# Filter must match the installed line (run-address-health-agent-droplet.sh);
# the old address_health_agent.py filter never matched, so every deploy
# appended a duplicate (28 copies accumulated by 2026-07-19).
( crontab -l 2>/dev/null \
    | grep -v 'run-address-health-agent-droplet.sh' \
    | grep -v 'address-health-agent/address_health_agent.py' \
    | awk '!seen[$0]++' || true
  echo "$CRON_LINE"
) | crontab -

echo "Installed address health cron (10 */12 * * * UTC)"
echo "Log: ${LOG}"
echo "Primary schedulers: Celery Beat (ADDRESS_HEALTH_AGENT_ENABLED) + GitHub Actions address-health-agent.yml"
echo "Operator admin browser agent: GitHub Actions operator-admin-agent.yml (daily 08:00 UTC)"
echo "Config: config/operator_agents.yaml"
