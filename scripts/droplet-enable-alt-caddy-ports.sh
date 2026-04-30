#!/usr/bin/env bash
# Append Caddy alternate host ports + internal TLS to deploy/.env on the Droplet when
# another service already owns 80/443. Idempotent (skips keys that already exist).
#
#   DROPLET=203.0.113.10 ./scripts/droplet-enable-alt-caddy-ports.sh
set -euo pipefail

: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
REMOTE_PATH="${REMOTE_PATH:-/opt/parking-acquisition-agents}"
SSH_USER="${SSH_USER:-root}"
HTTP_PORT="${CADDY_PUBLISH_HTTP:-9080}"
HTTPS_PORT="${CADDY_PUBLISH_HTTPS:-9443}"

ssh -oBatchMode=yes "${SSH_USER}@${DROPLET}" \
  "env REMOTE_PATH=$(printf '%q' "$REMOTE_PATH") HTTP_PORT=$(printf '%q' "$HTTP_PORT") HTTPS_PORT=$(printf '%q' "$HTTPS_PORT") bash -s" <<'EOS'
set -euo pipefail
ENV_FILE="${REMOTE_PATH}/deploy/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi
append_if_missing() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    echo "keep existing: $key"
  else
    printf '%s\n' "${key}=${val}" >> "$ENV_FILE"
    echo "appended: $key=$val"
  fi
}
append_if_missing CADDY_PUBLISH_HTTP "$HTTP_PORT"
append_if_missing CADDY_PUBLISH_HTTPS "$HTTPS_PORT"
append_if_missing CADDY_CADDYFILE ./Caddyfile.internal-tls
if grep -q 'YOUR_DB_HOST' "$ENV_FILE" 2>/dev/null; then
  echo "WARNING: DATABASE_URL still looks like a template (YOUR_DB_HOST). Fix before /ready will pass." >&2
fi
EOS
