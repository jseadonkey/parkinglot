#!/usr/bin/env bash
# Poll GET /internal/tasks/{task_id} until SUCCESS or FAILURE (or timeout).
#
# Usage:
#   export PUBLIC_API_URL=https://api.example.com
#   export INTERNAL_API_KEY=...   # optional if API has no internal key
#   ./scripts/poll_internal_celery_task.sh <task_id> [max_seconds]
#
# Or source deploy/.env first (PUBLIC_API_URL / INTERNAL_API_KEY).
#
set -euo pipefail

TASK_ID="${1:?usage: $0 <task_id> [max_seconds]}"
MAX_SEC="${2:-${POLL_TIMEOUT_SEC:-600}}"
INTERVAL="${POLL_INTERVAL_SEC:-3}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/deploy/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

BASE="${PUBLIC_API_URL:-${PHASE_A_API_BASE:-http://127.0.0.1:8000}}"
BASE="${BASE%/}"

HDR=()
if [[ -n "${INTERNAL_API_KEY:-}" ]]; then
  HDR=(-H "X-Internal-Key: ${INTERNAL_API_KEY}")
fi

elapsed=0
while [[ "$elapsed" -lt "$MAX_SEC" ]]; do
  json="$(curl -sS "${HDR[@]}" "${BASE}/internal/tasks/${TASK_ID}" -H "Accept: application/json")"
  state="$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))")"
  echo "$(date -Iseconds) state=$state"
  if [[ "$state" == "SUCCESS" ]]; then
    echo "$json" | python3 -m json.tool
    exit 0
  fi
  if [[ "$state" == "FAILURE" ]]; then
    echo "$json" | python3 -m json.tool
    exit 1
  fi
  sleep "$INTERVAL"
  elapsed=$((elapsed + INTERVAL))
done

echo "timeout after ${MAX_SEC}s waiting for task ${TASK_ID}"
exit 124
