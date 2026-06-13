#!/usr/bin/env bash
# Merge Langfuse keys into parkinglot Droplet deploy/.env (US host hardwired).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "${ROOT}/scripts/lib/droplet-target.sh"
# shellcheck source=lib/langfuse-target.sh
source "${ROOT}/scripts/lib/langfuse-target.sh"
assert_droplet_target "${ROOT}/scripts/set-langfuse-env-on-droplet.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

: "${LANGFUSE_PUBLIC_KEY:?Set LANGFUSE_PUBLIC_KEY}"
: "${LANGFUSE_SECRET_KEY:?Set LANGFUSE_SECRET_KEY}"

ENC_PK=$(printf '%s' "$LANGFUSE_PUBLIC_KEY" | base64 | tr -d '\n')
ENC_SK=$(printf '%s' "$LANGFUSE_SECRET_KEY" | base64 | tr -d '\n')
ENC_HOST=$(printf '%s' "$LANGFUSE_HOST" | base64 | tr -d '\n')
ENC_BASE=$(printf '%s' "$LANGFUSE_BASE_URL" | base64 | tr -d '\n')

ssh -o BatchMode=yes -o ConnectTimeout=30 "${SSH_USER}@${DROPLET}" \
  REMOTE_PATH="${REMOTE_PATH}" \
  ENC_PK="${ENC_PK}" \
  ENC_SK="${ENC_SK}" \
  ENC_HOST="${ENC_HOST}" \
  ENC_BASE="${ENC_BASE}" \
  bash -s <<'EOS'
set -euo pipefail
cd "$REMOTE_PATH"
test -f deploy/.env || { echo "error: deploy/.env missing on Droplet" >&2; exit 1; }
PK=$(printf '%s' "$ENC_PK" | base64 -d)
SK=$(printf '%s' "$ENC_SK" | base64 -d)
HOST=$(printf '%s' "$ENC_HOST" | base64 -d)
BASE=$(printf '%s' "$ENC_BASE" | base64 -d)
export PK SK HOST BASE
python3 <<'PY'
import os, pathlib
p = pathlib.Path("deploy/.env")
keys = ("LANGFUSE_PUBLIC_KEY=", "LANGFUSE_SECRET_KEY=", "LANGFUSE_HOST=", "LANGFUSE_BASE_URL=")
lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.startswith(keys)]
body = "\n".join(lines).rstrip() + "\n"
add = (
    "\n# Langfuse US — config/langfuse.yaml\n"
    f"LANGFUSE_PUBLIC_KEY={os.environ['PK']}\n"
    f"LANGFUSE_SECRET_KEY={os.environ['SK']}\n"
    f"LANGFUSE_HOST={os.environ['HOST']}\n"
    f"LANGFUSE_BASE_URL={os.environ['BASE']}\n"
)
p.write_text(body + add, encoding="utf-8", newline="\n")
print("Updated deploy/.env with Langfuse US host.")
PY
EOS

echo "Done. On Droplet run: ./scripts/droplet-crew-env-sync.sh && .venv/bin/parking-crew langfuse-check"
