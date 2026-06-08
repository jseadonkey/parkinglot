#!/usr/bin/env bash
# On the Droplet: if INTERNAL_API_KEY is empty in deploy/.env, set a random hex value
# and recreate api, worker, beat (and approval-ui if using the PostGIS compose pair).
#
# After this, copy INTERNAL_API_KEY from deploy/.env into GitHub secret
# SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY if you use deploy Slack notify from Actions.
#
#   ./scripts/droplet-provision-internal-api-key.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"
assert_droplet_target "$ROOT/scripts/droplet-provision-internal-api-key.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

ssh -oBatchMode=yes "${SSH_USER}@${DROPLET}" \
  "env REMOTE_PATH=$(printf '%q' "$REMOTE_PATH") bash -s" <<'EOS'
set -euo pipefail
cd "$REMOTE_PATH"
python3 <<'PY'
import secrets
from pathlib import Path

path = Path("deploy/.env")
lines = path.read_text(encoding="utf-8").splitlines()
val = ""
for ln in lines:
    if ln.startswith("INTERNAL_API_KEY="):
        val = ln.split("=", 1)[1].strip().strip('"').strip("'")
        break
if val:
    print("INTERNAL_API_KEY already set; not changing.")
    raise SystemExit(0)

key = secrets.token_hex(32)
out: list[str] = []
seen = False
for ln in lines:
    if ln.startswith("INTERNAL_API_KEY="):
        out.append(f"INTERNAL_API_KEY={key}")
        seen = True
    else:
        out.append(ln)
if not seen:
    while out and out[-1].strip() == "":
        out.pop()
    out.append(f"INTERNAL_API_KEY={key}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("INTERNAL_API_KEY was empty: set a new random value (not printed).")
PY
ARGS=(-f deploy/docker-compose.production.yml -f deploy/docker-compose.postgis-addon.yml --env-file deploy/.env)
if ! grep -q '^POSTGRES_PASSWORD=' deploy/.env 2>/dev/null; then
  ARGS=(-f deploy/docker-compose.production.yml --env-file deploy/.env)
fi
docker compose "${ARGS[@]}" up -d --force-recreate api worker worker-slack beat approval-ui
EOS
