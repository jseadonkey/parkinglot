#!/usr/bin/env bash
# Run ON the parkinglot Droplet: cd /opt/workspaces/parkinglot && ./scripts/droplet-crew-langfuse-setup.sh
# Langfuse host is hardwired to US (config/langfuse.yaml) — only paste API keys below.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lib/langfuse-target.sh
source "${ROOT}/scripts/lib/langfuse-target.sh"

: "${LANGFUSE_PUBLIC_KEY:?First run: export LANGFUSE_PUBLIC_KEY='pk-lf-...'}"
: "${LANGFUSE_SECRET_KEY:?First run: export LANGFUSE_SECRET_KEY='sk-lf-...'}"
export LANGFUSE_HOST="${LANGFUSE_HOST}"
export LANGFUSE_BASE_URL="${LANGFUSE_BASE_URL}"

echo "==> Updating deploy/.env with Langfuse keys (US host: ${LANGFUSE_HOST})"
python3 <<PY
import os, pathlib
p = pathlib.Path("deploy/.env")
if not p.is_file():
    raise SystemExit("error: deploy/.env missing")
keys = ("LANGFUSE_PUBLIC_KEY=", "LANGFUSE_SECRET_KEY=", "LANGFUSE_HOST=", "LANGFUSE_BASE_URL=")
lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.startswith(keys)]
body = "\n".join(lines).rstrip() + "\n"
add = (
    "\n# Langfuse US — config/langfuse.yaml + scripts/lib/langfuse-target.sh\n"
    f"LANGFUSE_PUBLIC_KEY={os.environ['LANGFUSE_PUBLIC_KEY']}\n"
    f"LANGFUSE_SECRET_KEY={os.environ['LANGFUSE_SECRET_KEY']}\n"
    f"LANGFUSE_HOST={os.environ['LANGFUSE_HOST']}\n"
    f"LANGFUSE_BASE_URL={os.environ['LANGFUSE_BASE_URL']}\n"
)
p.write_text(body + add, encoding="utf-8", newline="\n")
print("Updated deploy/.env")
PY
./scripts/set-langfuse-env-local.sh

if [[ ! -x .venv/bin/parking-crew ]]; then
  echo "==> Installing parking-crew (one-time, ~1 min)"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  ( cd services/crew && ../.venv/bin/pip install -q ".[observability]" )
fi

echo "==> Langfuse connection check (US cloud)"
.venv/bin/parking-crew langfuse-check
