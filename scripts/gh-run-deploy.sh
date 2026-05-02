#!/usr/bin/env bash
# Dispatch "Deploy to Droplet" from your laptop via GitHub CLI — same as clicking Run workflow.
#
# One-time setup:
#   brew install gh   # or https://cli.github.com/
#   gh auth login     # choose HTTPS, paste a token or browser login
#
# Usage:
#   ./scripts/gh-run-deploy.sh
#   REF=cursor/dual-scoring-agents-slack-channel POST_SLACK=all ./scripts/gh-run-deploy.sh
#   VERIFY_READY=false ./scripts/gh-run-deploy.sh   # skip /ready check (e.g. DNS not ready)
#
# Then in Cursor you can say: "run scripts/gh-run-deploy.sh" and the agent can execute it.
set -euo pipefail

REF="${REF:-cursor/dual-scoring-agents-slack-channel}"
POST_SLACK="${POST_SLACK:-all}"
VERIFY_READY="${VERIFY_READY:-false}"
USE_POSTGIS="${USE_POSTGIS:-true}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"

if ! command -v gh >/dev/null 2>&1; then
  echo "Install GitHub CLI: https://cli.github.com/  (then: gh auth login)" >&2
  exit 1
fi

# Resolve repo root (…/parkinglot) so gh runs in a git repo
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Dispatching Deploy to Droplet: ref=$REF post_slack_tasks=$POST_SLACK verify_public_ready=$VERIFY_READY"
gh workflow run deploy-droplet.yml \
  --ref "$REF" \
  -f "compose_file=$COMPOSE_FILE" \
  -f "verify_public_ready=$VERIFY_READY" \
  -f "slack_notify=false" \
  -f "post_slack_tasks=$POST_SLACK" \
  -f "use_local_postgis=$USE_POSTGIS"

echo "Started. Open: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions"
