#!/usr/bin/env bash
# Pipe the raw INTERNAL_API_KEY value (no "INTERNAL_API_KEY=" prefix) on stdin into GitHub Actions secret
# SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY for the current gh repo (must match deploy/.env on the Droplet).
#
# Prerequisites: GitHub CLI (`gh`) installed and authenticated for this repository.
#
# Example (from your laptop, after copying the key value only):
#   pbpaste | tr -d '\n' | ./scripts/gh-set-slack-notify-internal-secret.sh
#
# Or with explicit repo:
#   GH_REPO=owner/name pbpaste | tr -d '\n' | ./scripts/gh-set-slack-notify-internal-secret.sh
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "Install GitHub CLI: https://cli.github.com/" >&2
  exit 1
fi

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [ -z "$REPO" ]; then
  echo "Could not determine repo. Run from a git clone or set GH_REPO=owner/name." >&2
  exit 1
fi

KEY="$(cat)"
KEY="${KEY//$'\r'/}"
KEY="${KEY//$'\n'/}"
if [ -z "$KEY" ]; then
  echo "stdin was empty; not updating secret." >&2
  exit 1
fi

printf '%s' "$KEY" | gh secret set SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY --repo "$REPO"
echo "Set SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY on $REPO (value not printed)."
