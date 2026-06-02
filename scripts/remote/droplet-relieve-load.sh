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

echo "=== disable SCHEDULED_ENQUEUE_UNSCORED in deploy/.env ==="
python3 <<'PY'
import pathlib
import re

path = pathlib.Path("deploy/.env")
text = path.read_text(encoding="utf-8")
key = "SCHEDULED_ENQUEUE_UNSCORED_ENABLED"
if re.search(rf"^{re.escape(key)}=", text, re.M):
    text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}=false", text, count=1, flags=re.M)
else:
    text = text.rstrip() + f"\n{key}=false\n"
path.write_text(text, encoding="utf-8")
print(f"Set {key}=false")
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
echo "Done. Re-enable enqueue later with SCHEDULED_ENQUEUE_UNSCORED_ENABLED=true in deploy/.env and recreate beat."
