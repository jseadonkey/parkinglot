#!/usr/bin/env bash
# POST /internal/slack/digest-now and poll until the Celery task completes.
# Run on Droplet or laptop with reachability to PUBLIC_API_URL.
#
#   cd /opt/workspaces/parkinglot
#   set -a && source deploy/.env && set +a
#   ./scripts/slack_digest_now_wait.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/deploy/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

BASE="${PUBLIC_API_URL:-}"
if [[ -z "$BASE" ]]; then
  echo "error: set PUBLIC_API_URL (e.g. source deploy/.env)" >&2
  exit 2
fi
BASE="${BASE%/}"

HDR=(-H "Content-Type: application/json")
if [[ -n "${INTERNAL_API_KEY:-}" ]]; then
  HDR+=(-H "X-Internal-Key: ${INTERNAL_API_KEY}")
fi

echo "POST ${BASE}/internal/slack/digest-now"
RESP="$(curl -sS "${HDR[@]}" -X POST "${BASE}/internal/slack/digest-now")"
TASK_ID="$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])")"
echo "task_id=$TASK_ID"
exec "${ROOT}/scripts/poll_internal_celery_task.sh" "$TASK_ID"
