#!/usr/bin/env bash
# Quick check that KENT_ZONING and KING_ZONING are set and return at least one feature.
# Run before make phase-b-pipeline / build_king_kent_zoning_overlay.py.
#
#   export KENT_ZONING='https://…/FeatureServer/0'
#   export KING_ZONING='https://…/FeatureServer/0'
#   ./scripts/preflight_zoning_layers.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

if [[ -z "${KENT_ZONING:-}" || -z "${KING_ZONING:-}" ]]; then
  echo "error: export KENT_ZONING and KING_ZONING" >&2
  exit 2
fi

echo "=== Kent layer (first feature fields) ==="
"$PY" "${ROOT}/scripts/inspect_zoning_layer.py" "$KENT_ZONING"
echo
echo "=== King layer (first feature fields) ==="
"$PY" "${ROOT}/scripts/inspect_zoning_layer.py" "$KING_ZONING"
echo
echo "preflight OK"
