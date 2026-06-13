#!/usr/bin/env bash
# Hourly on the parkinglot Droplet: commit safe uncommitted work and rebuild production.
# Install: ./scripts/droplet-auto-commit-deploy-install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOCK_FILE="${ROOT}/ops/auto-commit-deploy.lock"
LOG="${ROOT}/ops/auto-commit-deploy.log"
STATE_FILE="${ROOT}/ops/auto-deploy-last-sha"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.production.yml}"

mkdir -p "${ROOT}/ops"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "auto-commit-deploy: already running" >>"$LOG"
  exit 0
fi

{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
} >>"$LOG"
exec >>"$LOG" 2>&1

if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "skip: not parkinglot Droplet workspace ($ROOT)"
  exit 0
fi

enabled="${AUTO_COMMIT_DEPLOY_ENABLED:-true}"
if [[ -f deploy/.env ]]; then
  line="$(grep -E '^AUTO_COMMIT_DEPLOY_ENABLED=' deploy/.env 2>/dev/null | tail -1 || true)"
  if [[ -n "$line" ]]; then
    val="${line#AUTO_COMMIT_DEPLOY_ENABLED=}"
    val="${val%$'\r'}"
    val="${val//\"/}"
    val="${val//\'/}"
    enabled="$val"
  fi
fi
case "$enabled" in
  1 | true | TRUE | yes | YES | on | ON) ;;
  *)
    echo "skip: AUTO_COMMIT_DEPLOY_ENABLED=$enabled"
    exit 0
    ;;
esac

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "skip: not a git repository"
  exit 0
fi

# Never auto-stage these paths (secrets + noisy deploy metadata).
EXCLUDE_PATHS=(
  deploy/.env
  .env
  config/langfuse.env
  ops/deploy-last-run.json
  ops/auto-commit-deploy.log
  ops/auto-commit-deploy.lock
)

has_committable_changes() {
  local line path skip ex
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    path="${line:3}"
    if [[ "$path" == *" -> "* ]]; then
      path="${path##* -> }"
    fi
    skip=0
    for ex in "${EXCLUDE_PATHS[@]}"; do
      if [[ "$path" == "$ex" || "$path" == "$ex/"* ]]; then
        skip=1
        break
      fi
    done
    [[ "$skip" -eq 0 ]] && return 0
  done < <(git status --porcelain)
  return 1
}

if ! has_committable_changes; then
  echo "skip: no committable uncommitted changes"
  exit 0
fi

echo "uncommitted work detected — staging safe paths"
git add -A
for ex in "${EXCLUDE_PATHS[@]}"; do
  if git ls-files --error-unmatch "$ex" >/dev/null 2>&1 || [[ -e "$ex" ]]; then
    git restore --staged "$ex" 2>/dev/null || true
  fi
done

if git diff --cached --quiet; then
  echo "skip: only excluded paths changed"
  exit 0
fi

branch="$(git branch --show-current)"
stamp="$(date -u +%Y-%m-%dT%H:%MZ)"
commit_msg="chore(droplet): auto-commit uncommitted work (${stamp})"

git commit -m "$commit_msg"
new_sha="$(git rev-parse HEAD)"
echo "committed ${new_sha} on ${branch}"

if git remote get-url origin >/dev/null 2>&1; then
  if git push -u origin "$branch"; then
    echo "pushed origin/${branch}"
  else
    echo "warn: git push failed (deploy continues from local tree)"
  fi
fi

echo "running API tests before deploy"
if ! bash "${ROOT}/scripts/run-api-tests.sh"; then
  echo "error: tests failed — commit kept, deploy skipped"
  exit 1
fi

if [[ -f "${ROOT}/scripts/check-mainline-parity.sh" ]]; then
  if ! bash "${ROOT}/scripts/check-mainline-parity.sh"; then
    echo "warn: mainline parity check failed — deploying anyway from local tree"
  fi
fi

if [[ ! -f deploy/.env ]]; then
  echo "error: deploy/.env missing — cannot rebuild production"
  exit 1
fi

compose_args=(-f "$COMPOSE_FILE" --env-file deploy/.env)
if [[ "${USE_LOCAL_POSTGIS:-}" == "1" || "${USE_LOCAL_POSTGIS:-}" == "true" ]]; then
  compose_args=(-f "$COMPOSE_FILE" -f deploy/docker-compose.postgis-addon.yml --env-file deploy/.env)
fi

echo "rebuilding production stack (${COMPOSE_FILE})"
docker compose "${compose_args[@]}" up -d --build
docker compose "${compose_args[@]}" ps

printf '%s\n' "$new_sha" >"$STATE_FILE"
echo "deployed ${new_sha} — recorded in ${STATE_FILE}"
