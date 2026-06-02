#!/usr/bin/env bash
# Write .droplet-project-id on the server so sync/rebuild cannot target the wrong repo path.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/droplet-target.sh
source "$ROOT/scripts/lib/droplet-target.sh"

assert_droplet_target "$ROOT/scripts/install-droplet-project-marker.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1

echo "Installing ${REMOTE_PATH}/.droplet-project-id = ${DROPLET_PROJECT_ID}"
ssh -o BatchMode=yes "${SSH_USER}@${DROPLET}" \
  "mkdir -p $(printf '%q' "$REMOTE_PATH") && \
   printf '%s\n' $(printf '%q' "$DROPLET_PROJECT_ID") > $(printf '%q' "$REMOTE_PATH")/.droplet-project-id && \
   chmod 644 $(printf '%q' "$REMOTE_PATH")/.droplet-project-id && \
   cat $(printf '%q' "$REMOTE_PATH")/.droplet-project-id"
echo "Done."
