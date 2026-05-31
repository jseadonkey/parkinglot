#!/usr/bin/env bash
# On the Droplet: if DATABASE_URL still contains YOUR_DB_HOST, set POSTGRES_PASSWORD and a
# matching DATABASE_URL for the optional PostGIS compose addon (postgres:5432, sslmode=disable).
#
#   DROPLET=203.0.113.10 ./scripts/droplet-provision-local-postgis-env.sh
set -euo pipefail

: "${DROPLET:?Set DROPLET to the Droplet IPv4 or hostname}"
REMOTE_PATH="${REMOTE_PATH:-/opt/parking-acquisition-agents}"
SSH_USER="${SSH_USER:-root}"

ssh -oBatchMode=yes "${SSH_USER}@${DROPLET}" \
  "env REMOTE_PATH=$(printf '%q' "$REMOTE_PATH") bash -s" <<'EOS'
set -euo pipefail
python3 <<'PY'
import os
import secrets
from pathlib import Path

path = Path(os.environ["REMOTE_PATH"]) / "deploy" / ".env"
text = path.read_text(encoding="utf-8")
if "YOUR_DB_HOST" not in text:
    print("DATABASE_URL does not contain YOUR_DB_HOST; not changing secrets.")
    raise SystemExit(0)

pw = secrets.token_hex(24)
out_lines: list[str] = []
for ln in text.splitlines():
    if ln.startswith("POSTGRES_PASSWORD=") or ln.startswith("DATABASE_URL="):
        continue
    out_lines.append(ln)
while out_lines and out_lines[-1].strip() == "":
    out_lines.pop()
out_lines.append(f"POSTGRES_PASSWORD={pw}")
out_lines.append(
    f"DATABASE_URL=postgresql+psycopg://parking_api:{pw}@postgres:5432/parking_app?sslmode=disable"
)
path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
print("provisioned POSTGRES_PASSWORD and DATABASE_URL for local PostGIS addon")
PY
EOS
