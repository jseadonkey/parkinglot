#!/usr/bin/env bash
# Commit and push safe working-tree changes from the parkinglot Droplet to origin/main.
# Installed via scripts/droplet-auto-commit-cron-install.sh (every 15 minutes).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "droplet-auto-commit: skip (not parkinglot Droplet path: $ROOT)" >&2
  exit 0
fi

LOCK="/tmp/parkinglot-auto-commit.lock"
LOG="/var/log/parkinglot-auto-commit.log"
mkdir -p "${ROOT}/data/operator-agent"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "droplet-auto-commit: another run in progress" >&2
  exit 0
fi

GIT_EMAIL="${DROPLET_AUTO_COMMIT_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
GIT_NAME="${DROPLET_AUTO_COMMIT_NAME:-parkinglot-droplet}"
BRANCH="${DROPLET_AUTO_COMMIT_BRANCH:-main}"
SKIP_CI="${DROPLET_AUTO_COMMIT_SKIP_CI:-1}"

git_cfg() {
  git -c "user.email=${GIT_EMAIL}" -c "user.name=${GIT_NAME}" "$@"
}

log() {
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"
}

# Never stage secrets, env backups, or large generated GIS caches.
unstage_forbidden() {
  git reset --quiet -- \
    deploy/.env \
    deploy/.env.* \
    services/crew/.env \
    .env \
    .env.local \
    .env.github \
    .env.github.* \
    terraform.tfstate \
    terraform.tfstate.* \
    data/benton \
    data/pierce \
    data/king \
    data/snohomish \
    data/kitsap \
    data/thurston \
    data/wa \
    'data/**/*.geojson' \
    data/operator-agent/*.json \
    data/operator-agent/*.log \
    data/operator-agent/.auto-commit.lock \
    services/crew/output/*.json \
    services/crew/output/*.md \
    2>/dev/null || true
}

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "error: not a git repository"
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  log "error: origin remote missing"
  exit 1
fi

git fetch origin "$BRANCH" --quiet 2>>"$LOG" || {
  log "error: git fetch failed"
  exit 1
}

if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
  exit 0
fi

git_cfg add -A
unstage_forbidden

if git diff --cached --quiet; then
  log "only forbidden paths changed; nothing to commit"
  exit 0
fi

summary="$(git diff --cached --name-only | head -20 | tr '\n' ' ' | sed 's/ $//')"
extra="$(( $(git diff --cached --name-only | wc -l) - 20 ))"
if (( extra > 0 )); then
  summary="${summary} (+${extra} more)"
fi

skip_tag=""
if [[ "$SKIP_CI" == "1" ]]; then
  skip_tag=" [skip ci]"
fi

msg="chore(droplet): auto-commit agent changes${skip_tag}

${summary}"

if ! git_cfg commit -m "$msg" >>"$LOG" 2>&1; then
  log "error: git commit failed"
  exit 1
fi

sha="$(git rev-parse --short HEAD)"
log "committed ${sha}: ${summary}"

if ! git_cfg pull --rebase origin "$BRANCH" >>"$LOG" 2>&1; then
  log "error: git pull --rebase failed; will retry on next cron run"
  git rebase --abort >>"$LOG" 2>&1 || true
  exit 1
fi

# Fallback backup: main history contains >100 MB GIS blobs that GitHub rejects,
# so pushing HEAD:main can fail forever. Push a clean tree-only snapshot branch
# (chained fast-forward) so an off-Droplet copy always exists.
push_snapshot_backup() {
  local snap_branch="droplet-snapshot"
  git fetch origin "$snap_branch" --quiet 2>>"$LOG" || true
  local parent
  parent="$(git rev-parse --verify --quiet "origin/${snap_branch}" \
    || git rev-parse --verify --quiet "origin/${BRANCH}")" || return 1
  local tree snap
  tree="$(git rev-parse "HEAD^{tree}")"
  if [[ "$(git rev-parse --verify --quiet "${parent}^{tree}")" == "$tree" ]]; then
    return 0  # nothing new to back up
  fi
  snap="$(git_cfg commit-tree "$tree" -p "$parent" \
    -m "droplet snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ) (tree of ${sha})")" || return 1
  if git_cfg push origin "${snap}:refs/heads/${snap_branch}" >>"$LOG" 2>&1; then
    log "pushed snapshot ${snap:0:9} (tree of ${sha}) to origin/${snap_branch}"
    return 0
  fi
  return 1
}

if ! git_cfg push origin "HEAD:${BRANCH}" >>"$LOG" 2>&1; then
  log "error: git push failed for ${sha}; trying snapshot backup"
  if ! push_snapshot_backup; then
    log "error: snapshot backup push also failed for ${sha}"
  fi
  exit 1
fi

log "pushed ${sha} to origin/${BRANCH}"
