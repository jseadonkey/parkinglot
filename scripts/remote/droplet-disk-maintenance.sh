#!/usr/bin/env bash
# Routine Droplet disk maintenance (safe to run on a schedule).
#
# - Docker: prune stopped containers, dangling images, build cache; if root ≥85%,
#   also prune all unused images (keeps images referenced by running containers).
# - Data: remove Baltimore Phase B staging GeoJSON when overlay already exists.
#
# Run on the Droplet from repo root:
#   bash scripts/remote/droplet-disk-maintenance.sh
#
# Or via GitHub Actions: workflow "Droplet disk maintenance" (weekly + on high-disk watchdog).
set -euo pipefail

if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "-" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
else
  ROOT="$(pwd)"
fi
cd "$ROOT"

AGGRESSIVE="${DISK_MAINTENANCE_AGGRESSIVE:-}"
USE_PCT=0
if DF_LINE="$(df -h / 2>/dev/null | tail -1)"; then
  USE_PCT="$(echo "$DF_LINE" | awk '{print $5}' | tr -d '%')"
  echo "=== disk before ==="
  echo "$DF_LINE"
else
  echo "=== disk before: (df failed) ==="
fi

if [ -n "$USE_PCT" ] && [ "$USE_PCT" -ge 85 ] 2>/dev/null; then
  AGGRESSIVE=1
  echo "=== root ≥85% — enabling aggressive image prune ==="
fi

echo ""
docker system df 2>/dev/null || true
echo ""

echo "=== docker container prune ==="
docker container prune -f 2>/dev/null || true

echo "=== docker image prune (dangling) ==="
docker image prune -f 2>/dev/null || true

echo "=== docker builder prune ==="
docker builder prune -f --keep-storage 2GB 2>/dev/null || docker builder prune -f 2>/dev/null || true

if [ -n "$AGGRESSIVE" ]; then
  echo "=== docker image prune -a (unused images only) ==="
  docker image prune -a -f 2>/dev/null || true
fi

BALT_DIR="$ROOT/data/baltimore"
OVERLAY="$BALT_DIR/baltimore_city_zoning_overlay.geojson"
if [ -f "$OVERLAY" ]; then
  echo "=== remove Baltimore staging GeoJSON (overlay present) ==="
  for f in baltimore_city_parcels.geojson baltimore_city_zoning_districts.geojson; do
    if [ -f "$BALT_DIR/$f" ]; then
      sz="$(du -h "$BALT_DIR/$f" | awk '{print $1}')"
      rm -f "$BALT_DIR/$f"
      echo "removed $BALT_DIR/$f ($sz)"
    fi
  done
fi

if [ -d "$ROOT/data" ]; then
  echo ""
  echo "=== largest data/ paths ==="
  du -sh "$ROOT/data"/* 2>/dev/null | sort -hr | head -8 || true
fi

echo ""
echo "=== disk after ==="
df -h /
docker system df 2>/dev/null || true

echo ""
echo "Done. If still ≥90%, resize the DO volume and run Droplet resources → grow_disk."
