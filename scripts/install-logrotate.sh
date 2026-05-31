#!/usr/bin/env bash
# Install logrotate for repo logs/*.log on the Droplet (pilot ingest, enqueue, finalize).
#
# Run once on the server from repo root (no SSH wrapper):
#   cd /opt/workspaces/parkinglot && sudo ./scripts/install-logrotate.sh
#
# Override repo path if needed:
#   REPO_ROOT=/opt/parking-acquisition-agents sudo ./scripts/install-logrotate.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${REPO_ROOT:-$ROOT}"
TEMPLATE="${ROOT}/deploy/logrotate/parkinglot-logs"
DEST="/etc/logrotate.d/parkinglot-logs"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Missing template: $TEMPLATE" >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Re-run with sudo so config can be written to ${DEST}." >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/logs"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed "s|@@REPO_ROOT@@|${REPO_ROOT}|g" "$TEMPLATE" > "$tmp"

echo "Installing ${DEST} for ${REPO_ROOT}/logs/*.log"
cp "$tmp" "$DEST"
chmod 644 "$DEST"

echo "--- logrotate dry-run ---"
logrotate -d "$DEST" 2>&1 | tail -40

echo "--- installed ---"
echo "Active config: ${DEST}"
echo "Cron/systemd runs logrotate daily via /etc/cron.daily/logrotate (Debian/Ubuntu)."
