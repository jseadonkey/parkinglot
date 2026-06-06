#!/usr/bin/env bash
# Reduce API/DB pressure: pause periodic pipeline enqueue, purge parking Celery backlog, restart workers.
#
# Run on Droplet from repo root:
#   COMPOSE_FILE=deploy/docker-compose.production.ghcr.yml bash scripts/remote/droplet-relieve-load.sh
set -euo pipefail

if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "-" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
else
  ROOT="$(pwd)"
fi
cd "$ROOT"
test -f deploy/.env

COMPOSE_REL="${COMPOSE_FILE:-deploy/docker-compose.production.ghcr.yml}"
ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)

echo "=== load / memory ==="
uptime
free -h
echo ""

echo "=== redis queue lengths (before) ==="
docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || echo "parking: (n/a)"
docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || echo "slack: (n/a)"
docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN celery 2>/dev/null || echo "celery: (n/a)"
echo ""

echo "=== pause heavy scheduled DB writers in deploy/.env ==="
python3 <<'PY'
import pathlib
import re

path = pathlib.Path("deploy/.env")
text = path.read_text(encoding="utf-8")
updates = {
    # Keep watchdog/reporting alive, but stop automatic write-heavy repairs while DB CPU recovers.
    "OPS_REMEDIATION_AUTO_FIX": "false",
    "SCHEDULED_ENQUEUE_UNSCORED_ENABLED": "false",
    "SCHEDULED_PRIORITY_PIPELINE_ENABLED": "false",
    "SCHEDULED_REFRESH_IDENTIFICATION_ENABLED": "false",
    "SCHEDULED_REFRESH_DEMAND_ENABLED": "false",
    "WA_STATEWIDE_ROLLOUT_ENABLED": "false",
    "EXPLORATION_CAMPAIGN_ENABLED": "false",
}
for key, value in updates.items():
    if re.search(rf"^{re.escape(key)}=", text, re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, count=1, flags=re.M)
    else:
        text = text.rstrip() + f"\n{key}={value}\n"
path.write_text(text, encoding="utf-8")
for key, value in updates.items():
    print(f"Set {key}={value}")
PY

echo ""
echo "=== purge parking Celery queue (keeps slack queue) ==="
docker compose "${ARGS[@]}" exec -T worker celery -A app.celery_app purge -f -Q parking 2>&1 || \
  docker compose "${ARGS[@]}" exec -T worker-slack celery -A app.celery_app purge -f -Q parking 2>&1 || true

echo ""
echo "=== restart beat + workers ==="
docker compose "${ARGS[@]}" up -d --force-recreate beat worker worker-slack

echo ""
echo "=== redis queue lengths (after) ==="
sleep 3
docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN parking 2>/dev/null || true
docker compose "${ARGS[@]}" exec -T redis redis-cli LLEN slack 2>/dev/null || true

echo ""
echo "=== docker stats snapshot ==="
docker stats --no-stream "${ARGS[@]}" 2>/dev/null | head -12 || docker stats --no-stream | head -12

echo ""
echo "Done. Re-enable selected schedulers later in deploy/.env and recreate beat when DB CPU is normal."
