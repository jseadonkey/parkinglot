#!/usr/bin/env bash
# Set PUBLIC_API_URL and CORS_ALLOW_ORIGINS to include the HTTPS host port from CADDY_PUBLISH_HTTPS
# (e.g. 9443) so the approval UI build and API CORS match alternate Caddy publishing.
#
#   DROPLET=203.0.113.10 ./scripts/droplet-sync-public-urls-to-caddy-port.sh
set -euo pipefail

: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
REMOTE_PATH="${REMOTE_PATH:-/opt/parking-acquisition-agents}"
SSH_USER="${SSH_USER:-root}"

ssh -oBatchMode=yes "${SSH_USER}@${DROPLET}" \
  "env REMOTE_PATH=$(printf '%q' "$REMOTE_PATH") bash -s" <<'EOS'
set -euo pipefail
cd "$REMOTE_PATH"
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
    raise SystemExit("missing UI_HOST or API_HOST in deploy/.env")

if https_port == "443":
    print("CADDY_PUBLISH_HTTPS is 443; leaving PUBLIC_API_URL / CORS unchanged.")
    raise SystemExit(0)

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
ARGS=(-f deploy/docker-compose.production.yml -f deploy/docker-compose.postgis-addon.yml --env-file deploy/.env)
if grep -q '^POSTGRES_PASSWORD=' deploy/.env 2>/dev/null; then
  :
else
  ARGS=(-f deploy/docker-compose.production.yml --env-file deploy/.env)
fi
docker compose "${ARGS[@]}" up -d --build approval-ui
docker compose "${ARGS[@]}" up -d --force-recreate api worker beat
EOS
