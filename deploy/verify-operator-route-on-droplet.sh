#!/usr/bin/env bash
# Run on the Droplet from the repo root (same cwd as `docker compose`).
# Confirms Caddy mounts an operator → operator-console stanza and the upstream responds.
set -euo pipefail
COMPOSE=${COMPOSE:-deploy/docker-compose.production.yml}
ENV_FILE=${ENV_FILE:-deploy/.env}

echo "=== Caddyfile mounted in container (first 30 lines) ==="
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" exec -T caddy sed -n '1,30p' /etc/caddy/Caddyfile

echo ""
echo "=== grep operator reverse_proxy ==="
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" exec -T caddy grep -n operator /etc/caddy/Caddyfile || true

echo ""
echo "=== wget operator-console from inside caddy network ==="
docker compose -f "$COMPOSE" --env-file "$ENV_FILE" exec -T caddy wget -qSO- --timeout=5 http://operator-console:3000/operator 2>&1 | head -25
