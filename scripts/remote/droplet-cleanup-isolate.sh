#!/usr/bin/env bash
# Reclaim disk and isolate the parkinglot stack on a shared Droplet.
#
# Run on the Droplet from repo root (after deploy sync):
#   COMPOSE_FILE=deploy/docker-compose.production.ghcr.yml bash scripts/remote/droplet-cleanup-isolate.sh
#
# Safe for production parkinglot: stops known non-parking containers on this VM,
# removes compose orphans, prunes unused Docker data, recreates the GHCR stack.
set -euo pipefail

if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "-" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
else
  ROOT="$(pwd)"
fi
cd "$ROOT"
test -f deploy/.env

COMPOSE_REL="${COMPOSE_FILE:-deploy/docker-compose.production.ghcr.yml}"
if [[ ! -f "$COMPOSE_REL" ]]; then
  COMPOSE_REL="deploy/docker-compose.production.ghcr.yml"
fi
ARGS=(-f "$COMPOSE_REL" --env-file deploy/.env)

echo "=== disk before ==="
df -h /
echo ""
docker system df || true
echo ""

echo "=== running containers (all projects) ==="
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' || true
echo ""

# Containers that are not part of the current parkinglot compose file but share the deploy project name.
PARKING_SERVICES="redis api worker beat approval-ui operator-console caddy"
echo "=== stop/remove non-parking containers on this Droplet ==="
while IFS= read -r name; do
  [[ -z "$name" ]] && continue
  base="${name#deploy-}"
  base="${base%-1}"
  skip=false
  for svc in $PARKING_SERVICES; do
    if [[ "$base" == "$svc" ]]; then
      skip=true
      break
    fi
  done
  if [[ "$skip" == true ]]; then
    continue
  fi
  echo "stopping $name"
  docker stop "$name" 2>/dev/null || true
  docker rm "$name" 2>/dev/null || true
done < <(docker ps -a --format '{{.Names}}' | grep -E '^deploy-' || true)

# Other compose projects observed on the shared VM (not parkinglot).
for name in multi-pol-listener-main_monitor-1 multi-pol-listener-webhook-1; do
  if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
    echo "stopping $name"
    docker stop "$name" 2>/dev/null || true
    docker rm "$name" 2>/dev/null || true
  fi
done

echo ""
echo "=== recreate parkinglot stack (--remove-orphans) ==="
docker compose "${ARGS[@]}" pull api worker beat redis 2>/dev/null || true
docker compose "${ARGS[@]}" up -d --remove-orphans --build
docker compose "${ARGS[@]}" ps

echo ""
echo "=== docker prune (stopped containers, dangling images, build cache) ==="
docker container prune -f
docker image prune -f
docker builder prune -f --keep-storage 3GB 2>/dev/null || docker builder prune -f || true
# Unused images not referenced by any container (keeps running stack images).
docker image prune -a -f --filter "until=72h" 2>/dev/null || docker image prune -a -f

echo ""
echo "=== largest docker dirs ==="
du -sh /var/lib/docker/* 2>/dev/null | sort -hr | head -8 || true
echo ""
echo "=== largest data/ files (repo) ==="
if [[ -d "$ROOT/data" ]]; then
  du -sh "$ROOT/data"/* 2>/dev/null | sort -hr | head -10 || true
fi

echo ""
echo "=== disk after ==="
df -h /
echo ""
docker system df || true

echo ""
echo "Done. Add DigitalOcean volume or resize disk when ready; target <70% used on /."
