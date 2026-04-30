#!/usr/bin/env bash
# On the Droplet: allow Caddy alternate HTTP/HTTPS host ports through UFW (idempotent).
# Defaults match deploy/.env examples (9080 / 9443).
#
#   DROPLET=203.0.113.10 HTTP_PORT=9080 HTTPS_PORT=9443 ./scripts/droplet-open-caddy-alt-ports-ufw.sh
set -euo pipefail

: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
SSH_USER="${SSH_USER:-root}"
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
