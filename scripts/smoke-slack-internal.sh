#!/usr/bin/env bash
# Curl Slack-related /internal/* routes against a running API (local or production).
#
# Usage:
#   export PUBLIC_API_URL="https://api.example.com"   # no trailing slash
#   export INTERNAL_API_KEY="..."                    # optional if API has no key
#   ./scripts/smoke-slack-internal.sh
#
# Optional (posts to the real channel / enqueues worker work):
#   SLACK_SMOKE_POST_TEST=1      — POST /internal/slack/test-message (API container → Slack)
#   SLACK_SMOKE_DIGEST_NOW=1     — POST /internal/slack/digest-now + one poll (worker → Slack)
#
# Or pass base URL as first argument (still uses INTERNAL_API_KEY from env when set).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE="${1:-${PUBLIC_API_URL:-}}"
if [[ -z "$BASE" ]]; then
  echo "Set PUBLIC_API_URL or pass base URL as first argument (e.g. https://host)." >&2
  exit 1
fi
BASE="${BASE%/}"

pretty_json() {
  if command -v jq >/dev/null 2>&1; then
    jq .
  else
    python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2))" 2>/dev/null || cat
  fi
}

CURL=(curl -fsS --connect-timeout 10 --max-time 45)
HDR=()
if [[ -n "${INTERNAL_API_KEY:-}" ]]; then
  HDR=(-H "X-Internal-Key: ${INTERNAL_API_KEY}")
fi

echo "==> GET ${BASE}/internal/slack/status" >&2
"${CURL[@]}" "${HDR[@]}" "${BASE}/internal/slack/status" | pretty_json

echo "==> GET ${BASE}/internal/slack/last-digest" >&2
"${CURL[@]}" "${HDR[@]}" "${BASE}/internal/slack/last-digest" | pretty_json

if [[ "${SLACK_SMOKE_POST_TEST:-}" == "1" ]]; then
  echo "==> POST ${BASE}/internal/slack/test-message (SLACK_SMOKE_POST_TEST=1)" >&2
  body_json="$(python3 -c "import json,os; print(json.dumps({'text': os.environ.get('SLACK_SMOKE_TEXT','Parking agents: API smoke test (ok to delete)')}))")"
  "${CURL[@]}" -X POST "${HDR[@]}" \
    -H "Content-Type: application/json" \
    -d "$body_json" \
    "${BASE}/internal/slack/test-message" | pretty_json
fi

if [[ "${SLACK_SMOKE_DIGEST_NOW:-}" == "1" ]]; then
  echo "==> POST ${BASE}/internal/slack/digest-now (SLACK_SMOKE_DIGEST_NOW=1)" >&2
  tid="$(
    "${CURL[@]}" -X POST "${HDR[@]}" \
      -H "Content-Type: application/json" \
      -d '{}' \
      "${BASE}/internal/slack/digest-now" | python3 -c "import json,sys; print(json.load(sys.stdin).get('task_id',''))"
  )"
  if [[ -z "$tid" ]]; then
    echo "FAIL: no task_id from digest-now" >&2
    exit 1
  fi
  echo "    task_id=$tid — polling once (wait ~3s) …" >&2
  sleep 3
  echo "==> GET ${BASE}/internal/tasks/${tid}" >&2
  "${CURL[@]}" "${HDR[@]}" "${BASE}/internal/tasks/${tid}" | pretty_json
fi

echo "OK" >&2
