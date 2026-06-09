#!/usr/bin/env bash
# CI-style checks for operator + address health automation (no secrets, no Droplet).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> workflow files"
for wf in address-health-agent.yml operator-admin-agent.yml deploy-droplet.yml container-images.yml; do
  test -f ".github/workflows/${wf}"
  echo "  OK .github/workflows/${wf}"
done
if grep -q 'make droplet-sync' .github/workflows/address-health-agent.yml; then
  echo "error: address-health-agent.yml must not use make droplet-sync (GHA has no ssh alias parkinglot)" >&2
  exit 1
fi
if ! grep -q 'sync-to-droplet.sh' .github/workflows/address-health-agent.yml; then
  echo "error: address-health-agent.yml must sync via scripts/sync-to-droplet.sh + DROPLET_HOST" >&2
  exit 1
fi

echo "==> config/operator_agents.yaml"
python3 - <<'PY'
from pathlib import Path

text = Path("config/operator_agents.yaml").read_text(encoding="utf-8")
for needle in ("address_health_agent", "operator_admin_agent", "backfill-wa-centroid-addresses"):
    assert needle in text, f"missing {needle!r} in config/operator_agents.yaml"
PY

echo "==> bash syntax"
for f in \
  scripts/droplet-operator-agents-install.sh \
  scripts/droplet-post-deploy-operator-agents.sh \
  scripts/droplet-operator-agent-install.sh \
  scripts/validate-operator-agents.sh
do
  bash -n "$f"
  echo "  OK $f"
done

echo "==> jurisdiction registry"
make validate-jurisdictions

echo "==> OpenAPI includes WA centroid backfill"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "error: need python3 or .venv" >&2
  exit 1
fi
"$PY" scripts/export_openapi_json.py -o /tmp/openapi-operator-agents.json
"$PY" - <<'PY'
import json

paths = json.load(open("/tmp/openapi-operator-agents.json"))["paths"]
assert "/internal/metrics/backfill-wa-centroid-addresses" in paths
print("  OK /internal/metrics/backfill-wa-centroid-addresses")
PY

echo "==> address health agent syntax"
python3 -m py_compile scripts/address-health-agent/address_health_agent.py
python3 -m py_compile scripts/operator-admin-agent/droplet-remediate.py

echo "validate-operator-agents: OK"
