#!/usr/bin/env bash
# Merge Langfuse keys into services/crew/.env from your shell (never commit this file).
#
# Usage (paste keys in Terminal, not in Cursor chat):
#   export LANGFUSE_PUBLIC_KEY=pk-lf-...
#   export LANGFUSE_SECRET_KEY=sk-lf-...
#   export LANGFUSE_PUBLIC_KEY=pk-lf-...
#   export LANGFUSE_SECRET_KEY=sk-lf-...
#   ./scripts/set-langfuse-env-local.sh
# Host URL is hardwired US — see config/langfuse.yaml (do not set LANGFUSE_HOST manually).
#
# Then verify:
#   make langfuse-check
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/services/crew/.env"
EXAMPLE="${ROOT}/services/crew/.env.example"
# shellcheck source=lib/langfuse-target.sh
source "${ROOT}/scripts/lib/langfuse-target.sh"

test -n "${LANGFUSE_PUBLIC_KEY:-}" || { echo "export LANGFUSE_PUBLIC_KEY first"; exit 1; }
test -n "${LANGFUSE_SECRET_KEY:-}" || { echo "export LANGFUSE_SECRET_KEY first"; exit 1; }
export LANGFUSE_HOST LANGFUSE_BASE_URL

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$EXAMPLE" "$ENV_FILE"
fi

upsert() {
  local key="$1" val="$2" file="$3"
  python3 - "$key" "$val" "$file" <<'PY'
import pathlib, sys
key, val, path = sys.argv[1:4]
text = pathlib.Path(path).read_text(encoding="utf-8")
lines = [ln for ln in text.splitlines() if not ln.startswith(key + "=")]
body = "\n".join(lines).rstrip()
pathlib.Path(path).write_text((body + "\n" if body else "") + f"{key}={val}\n", encoding="utf-8")
PY
}

upsert LANGFUSE_PUBLIC_KEY "$LANGFUSE_PUBLIC_KEY" "$ENV_FILE"
upsert LANGFUSE_SECRET_KEY "$LANGFUSE_SECRET_KEY" "$ENV_FILE"
upsert LANGFUSE_HOST "$LANGFUSE_HOST" "$ENV_FILE"
upsert LANGFUSE_BASE_URL "$LANGFUSE_BASE_URL" "$ENV_FILE"

echo "Updated ${ENV_FILE} (Langfuse US host: ${LANGFUSE_HOST})."
echo "Run: .venv/bin/parking-crew langfuse-check"
