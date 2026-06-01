#!/usr/bin/env bash
# Run ON the Droplet (or via GitHub Actions SSH). Use when Docker reports:
#   Bind for 0.0.0.0:80 failed: port is already allocated
#
# Sets CADDY to publish on 9080/9443 + internal TLS, updates PUBLIC_API_URL / CORS for :9443,
# opens UFW if present, then docker compose up -d --build.
#
#   sudo bash scripts/droplet_apply_caddy_alt_ports.sh
#   sudo bash scripts/droplet_apply_caddy_alt_ports.sh /opt/parking-acquisition-agents
set -euo pipefail

REPO_ROOT="${1:-/opt/parking-acquisition-agents}"
cd "$REPO_ROOT"
ENV_FILE="${REPO_ROOT}/deploy/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

HTTP_PORT="${CADDY_PUBLISH_HTTP:-9080}"
HTTPS_PORT="${CADDY_PUBLISH_HTTPS:-9443}"

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

python3 <<'PY'
from pathlib import Path

path = Path("deploy/.env")
lines = path.read_text(encoding="utf-8").splitlines()

def get(key: str) -> str:
    for ln in lines:
        if ln.startswith(f"{key}="):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

ui = get("UI_HOST")
api = get("API_HOST")
https_port = get("CADDY_PUBLISH_HTTPS") or "443"
if not ui or not api:
    raise SystemExit("missing UI_HOST or API_HOST in deploy/.env — set them first")

if https_port == "443":
    print("CADDY_PUBLISH_HTTPS is 443; leaving PUBLIC_API_URL / CORS unchanged.")
else:
    new_public = f"https://{api}:{https_port}"
    new_cors = f"https://{ui}:{https_port}"
    out = []
    seen_p = seen_c = False
    for ln in lines:
        if ln.startswith("PUBLIC_API_URL="):
            out.append(f"PUBLIC_API_URL={new_public}")
            seen_p = True
        elif ln.startswith("CORS_ALLOW_ORIGINS="):
            out.append(f"CORS_ALLOW_ORIGINS={new_cors}")
            seen_c = True
        else:
            out.append(ln)
    if not seen_p:
        out.append(f"PUBLIC_API_URL={new_public}")
    if not seen_c:
        out.append(f"CORS_ALLOW_ORIGINS={new_cors}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print("updated PUBLIC_API_URL and CORS_ALLOW_ORIGINS for HTTPS port", https_port)
PY

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "${HTTP_PORT}/tcp" || true
  ufw allow "${HTTPS_PORT}/tcp" || true
  echo "ufw: allowed ${HTTP_PORT}/tcp and ${HTTPS_PORT}/tcp"
fi

COMPOSE=(docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env)
if grep -q '^POSTGRES_PASSWORD=' deploy/.env 2>/dev/null; then
  COMPOSE+=( -f deploy/docker-compose.postgis-addon.yml )
fi

"${COMPOSE[@]}" up -d --build
"${COMPOSE[@]}" ps

echo "Done. If 80/443 were busy, Caddy should be Up on host ports ${HTTP_PORT} and ${HTTPS_PORT}."
