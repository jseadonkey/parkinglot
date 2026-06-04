#!/usr/bin/env bash
# Append Caddy alternate host ports + internal TLS to deploy/.env on the Droplet when
# another service already owns 80/443. Idempotent (skips keys that already exist).
#
#   ./scripts/droplet-enable-alt-caddy-ports.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/droplet-enable-alt-caddy-ports.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

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
