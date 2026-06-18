#!/usr/bin/env bash
# Turn on capacity-gated WA parcel ingest (Phase A), zoning merge (Phase B), and priority pipeline.
# Runs automatically from deploy-droplet.yml after every production deploy.
#
# Usage (on Droplet, repo root):
#   COMPOSE_FILE=deploy/docker-compose.production.ghcr.yml ./scripts/ensure-wa-ingest-automation.sh
#
# Env:
#   KICKSTART_WA_AUTOMATION — default true; POST wa-rollout-now + wa-phase-b-rollout-now when INTERNAL_API_KEY set
#   DEPLOY_ENV_FILE — default deploy/.env
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/deploy/.env}"
COMPOSE_REL="${COMPOSE_FILE:-deploy/docker-compose.production.ghcr.yml}"
if [[ ! -f "$COMPOSE_REL" ]]; then
  COMPOSE_REL="deploy/docker-compose.production.yml"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

_env_val() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE" \
    | tr -d '\r' \
    | sed 's/^"//;s/"$//'
}

echo "==> ensure WA ingest automation (Phase A + Phase B + priority pipeline)"

ENV_OUT="$(python3 - <<'PY' "$ENV_FILE"
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
updates = {
    "GEO_MARKETS_CONFIG_PATH": "/app/config/geo_markets.yaml",
    "WA_STATEWIDE_ROLLOUT_ENABLED": "true",
    "WA_STATEWIDE_ROLLOUT_CONFIG_PATH": "/app/config/wa_statewide_rollout.yaml",
    "WA_STATEWIDE_ROLLOUT_CRONTAB_HOUR": "*",
    "WA_STATEWIDE_ROLLOUT_CRONTAB_MINUTE": "15",
    "WA_PHASE_B_ROLLOUT_ENABLED": "true",
    "WA_PHASE_B_ROLLOUT_CONFIG_PATH": "/app/config/wa_phase_b_rollout.yaml",
    "WA_PHASE_B_ROLLOUT_CRONTAB_HOUR": "*",
    "WA_PHASE_B_ROLLOUT_CRONTAB_MINUTE": "45",
    "SCHEDULED_PRIORITY_PIPELINE_ENABLED": "true",
    "SCHEDULED_PRIORITY_PIPELINE_LIMIT": "75",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_HOUR": "*/2",
    "SCHEDULED_PRIORITY_PIPELINE_CRONTAB_MINUTE": "20",
    "SCHEDULED_ENQUEUE_UNSCORED_LIMIT": "75",
}
lines = path.read_text(encoding="utf-8").splitlines()
keys = set(updates)
out: list[str] = []
seen: set[str] = set()
changed = False
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in keys:
        new_line = f"{key}={updates[key]}"
        if line.strip() != new_line:
            changed = True
        out.append(new_line)
        seen.add(key)
    else:
        out.append(line)
missing = [k for k in keys if k not in seen]
if missing:
    changed = True
    if out and out[-1].strip():
        out.append("")
    out.append("# WA ingest automation — enabled on every deploy (Phase A + Phase B + priority pipeline)")
    for key in sorted(missing):
        out.append(f"{key}={updates[key]}")
if changed:
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("ENV_UPDATED=1" if changed else "ENV_UPDATED=0")
for key, val in sorted(updates.items()):
    print(f"  {key}={val}")
PY
)"
echo "$ENV_OUT"

if echo "$ENV_OUT" | grep -q '^ENV_UPDATED=1$'; then
  echo "==> deploy/.env changed — recreating api worker beat"
  docker compose -f "$COMPOSE_REL" --env-file deploy/.env up -d --no-deps api worker beat
else
  echo "==> deploy/.env already has WA automation flags"
fi

KICKSTART="${KICKSTART_WA_AUTOMATION:-true}"
KEY="$(_env_val INTERNAL_API_KEY)"
BASE="$(_env_val PUBLIC_API_URL)"
if [[ -z "$BASE" ]]; then
  H="$(_env_val API_HOST)"
  [[ -n "$H" ]] && BASE="https://$H"
fi

_internal_post() {
  local path="$1"
  local url="${BASE%/}${path}"
  if [[ -z "$KEY" ]]; then
    echo "skip POST $path (no INTERNAL_API_KEY)"
    return 0
  fi
  echo "POST $url"
  set +e
  curl -fsSk --connect-timeout 15 --max-time 120 -X POST "$url" \
    -H "Content-Type: application/json" \
    -H "X-Internal-Key: $KEY" \
    -d '{}'
  local ec=$?
  set -e
  if [[ "$ec" -ne 0 ]]; then
    echo "POST $path returned $ec (deferred — Beat will retry)" >&2
  fi
  echo
}

if [[ "$KICKSTART" == "true" ]]; then
  echo "==> kickstart WA loops when capacity allows"
  _internal_post "/internal/ingest/wa-rollout-now"
  _internal_post "/internal/ingest/wa-phase-b-rollout-now"
else
  echo "==> kickstart skipped (KICKSTART_WA_AUTOMATION=$KICKSTART)"
fi

echo "==> ensure WA ingest automation complete"
