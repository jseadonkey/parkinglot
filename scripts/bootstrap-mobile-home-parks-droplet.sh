#!/usr/bin/env bash
# One-time: prepare mobile-home-parks Droplet path and clone GitHub repo (no Mac folder needed).
# Prerequisite: GitHub repo jseadonkey/mobile-home-parks exists and Droplet can reach github.com.
set -euo pipefail

MHP_HOST="${MHP_SSH_HOST:-mobile-home-parks}"
MHP_PATH="${MHP_REMOTE_PATH:-/opt/workspaces/mobile-home-parks}"
MHP_REPO="${MHP_GITHUB_REPO:-git@github.com:jseadonkey/mobile-home-parks.git}"

echo "Bootstrap mobile-home-parks on host=${MHP_HOST} path=${MHP_PATH}"

resolved="$(ssh -G "$MHP_HOST" 2>/dev/null | awk '/^hostname / { print $2; exit }')"
if [[ "$resolved" == "209.38.142.108" ]]; then
  echo "error: ${MHP_HOST} resolves to parkinglot IP — fix ~/.ssh/config" >&2
  exit 1
fi

ssh -o BatchMode=yes "root@${MHP_HOST}" bash -s <<EOS
set -euo pipefail
MHP_PATH=$(printf '%q' "$MHP_PATH")
MHP_REPO=$(printf '%q' "$MHP_REPO")
mkdir -p ~/.ssh
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null || true
if [[ ! -f ~/.ssh/github_deploy ]]; then
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/github_deploy -C "mhp-droplet-deploy"
  echo "Add this deploy key to GitHub repo mobile-home-parks (read-only):"
  cat ~/.ssh/github_deploy.pub
  echo "Then re-run this script."
  exit 2
fi
export GIT_SSH_COMMAND='ssh -i ~/.ssh/github_deploy -o IdentitiesOnly=yes'
mkdir -p "\$MHP_PATH"
if [[ -d "\$MHP_PATH/.git" ]]; then
  echo "Already a git repo at \$MHP_PATH — git pull"
  cd "\$MHP_PATH" && git pull --ff-only || true
else
  echo "Cloning \$MHP_REPO into \$MHP_PATH"
  git clone "\$MHP_REPO" "\$MHP_PATH"
fi
echo mobile-home-parks > "\$MHP_PATH/.droplet-project-id"
chmod 644 "\$MHP_PATH/.droplet-project-id"
ls -la "\$MHP_PATH" | head -10
cat "\$MHP_PATH/.droplet-project-id"
EOS

echo ""
echo "Next: Cursor → Remote-SSH → ${MHP_HOST} → Open Folder → ${MHP_PATH}"
