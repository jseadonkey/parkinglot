#!/usr/bin/env bash
# On the Droplet: allow Caddy alternate HTTP/HTTPS host ports through UFW (idempotent).
# Defaults match deploy/.env examples (9080 / 9443).
#
#   HTTP_PORT=9080 HTTPS_PORT=9443 ./scripts/droplet-open-caddy-alt-ports-ufw.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/droplet-open-caddy-alt-ports-ufw.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1
HTTP_PORT="${HTTP_PORT:-9080}"
HTTPS_PORT="${HTTPS_PORT:-9443}"

ssh -oBatchMode=yes "${SSH_USER}@${DROPLET}" \
  "env HTTP_PORT=$(printf '%q' "$HTTP_PORT") HTTPS_PORT=$(printf '%q' "$HTTPS_PORT") bash -s" <<'EOS'
set -euo pipefail
if command -v ufw >/dev/null 2>&1; then
  ufw allow "${HTTP_PORT}/tcp"
  ufw allow "${HTTPS_PORT}/tcp"
  ufw status numbered
else
  echo "ufw not installed; skipping firewall changes."
fi
EOS
