#!/usr/bin/env bash
# CrewAI secrets: production lives on the Droplet only.
#
# ON DROPLET (primary):
#   cd /opt/workspaces/parkinglot && ./scripts/droplet-crew-env-sync.sh
#
# ON MAC (discouraged — dev mirror only):
#   ./scripts/sync-crew-secrets.sh --pull-from-droplet
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREW_ENV="${ROOT}/services/crew/.env"
EXAMPLE="${ROOT}/services/crew/.env.example"
FROM_DROPLET=0
ON_DROPLET=0

if [[ "$ROOT" == /opt/workspaces/parkinglot* ]]; then
  ON_DROPLET=1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --on-droplet) ON_DROPLET=1; shift ;;
    --pull-from-droplet) FROM_DROPLET=1; shift ;;
    --no-droplet) FROM_DROPLET=0; shift ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

KEYS=(
  OPENAI_API_KEY ANTHROPIC_API_KEY AZURE_OPENAI_API_KEY CREWAI_LLM
  DATABASE_URL CREW_DATABASE_URL
  SERPER_API_KEY TAVILY_API_KEY
  GITHUB_TOKEN GITHUB_REPO GITHUB_BASE_BRANCH
  SLACK_BOT_TOKEN SLACK_DIGEST_CHANNEL_ID SLACK_AGENT_DISCUSSION_CHANNEL_ID SLACK_ADMIN_CHANNEL_ID
  LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST LANGFUSE_BASE_URL
  FINOPS_LOG_COMMAND FINOPS_DB_STATS_COMMAND
  INTERNAL_API_KEY BATCHDATA_API_KEY
)

if [[ "$ON_DROPLET" != "1" && "$FROM_DROPLET" != "1" ]]; then
  echo "Crew secrets are stored on the parkinglot Droplet (deploy/.env), not on the Mac clone." >&2
  echo "  SSH: cd /opt/workspaces/parkinglot && ./scripts/droplet-crew-env-sync.sh" >&2
  echo "  Dev mirror only: $0 --pull-from-droplet" >&2
  exit 0
fi

if [[ ! -f "$CREW_ENV" ]]; then
  cp "$EXAMPLE" "$CREW_ENV"
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cp "$CREW_ENV" "$TMP"

merge_line() {
  local key="$1" val="$2" file="$3"
  [[ -n "$val" ]] || return 0
  python3 - "$key" "$val" "$file" <<'PY'
import pathlib, sys
key, val, path = sys.argv[1:4]
text = pathlib.Path(path).read_text(encoding="utf-8")
lines = [ln for ln in text.splitlines() if not ln.startswith(key + "=")]
body = "\n".join(lines).rstrip()
pathlib.Path(path).write_text((body + "\n" if body else "") + f"{key}={val}\n", encoding="utf-8")
PY
}

for key in "${KEYS[@]}"; do
  val="${!key:-}"
  [[ -n "$val" ]] && merge_line "$key" "$val" "$TMP"
done

if [[ "$ON_DROPLET" == "1" ]]; then
  SRC="${ROOT}/deploy/.env"
else
  for src in "${ROOT}/deploy/.env" "${ROOT}/.env"; do
    [[ -f "$src" ]] || continue
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%%#*}"
      line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
      [[ -z "$line" || "$line" != *"="* ]] && continue
      key="${line%%=*}"
      val="${line#*=}"
      for want in "${KEYS[@]}"; do
        [[ "$key" == "$want" && -n "$val" ]] && merge_line "$key" "$val" "$TMP"
      done
    done <"$src"
  done
  SRC=""
fi

if [[ -n "${SRC:-}" && -f "$SRC" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$line" || "$line" != *"="* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    for want in "${KEYS[@]}"; do
      [[ "$key" == "$want" && -n "$val" ]] && merge_line "$key" "$val" "$TMP"
    done
  done <"$SRC"
fi

if [[ "$FROM_DROPLET" == "1" && "$ON_DROPLET" != "1" ]]; then
  # shellcheck source=lib/droplet-target.sh
  source "${ROOT}/scripts/lib/droplet-target.sh"
  assert_droplet_target "${ROOT}/scripts/sync-crew-secrets.sh" "${DROPLET:-}" "${REMOTE_PATH:-}" "${SSH_USER:-}" || exit 1
  PATTERN="$(IFS='|'; echo "${KEYS[*]}")"
  ssh -o BatchMode=yes -o ConnectTimeout=30 "${SSH_USER}@${DROPLET}" \
    "grep -E '^(${PATTERN})=' '${REMOTE_PATH}/deploy/.env' 2>/dev/null || true" >"${TMP}.droplet" || true
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" == *"="* ]] || continue
    merge_line "${line%%=*}" "${line#*=}" "$TMP"
  done <"${TMP}.droplet"
  rm -f "${TMP}.droplet"
  echo "warning: copied production secrets to Mac clone (dev mirror). Prefer running crew on Droplet." >&2
fi

python3 - "$TMP" "$ON_DROPLET" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
on_droplet = sys.argv[2] == "1"
lines = path.read_text(encoding="utf-8").splitlines()
data = {}
order = []
for ln in lines:
    if not ln or ln.startswith("#") or "=" not in ln:
        order.append(ln)
        continue
    k, _, v = ln.partition("=")
    if k not in data:
        order.append(k)
    data[k] = v

def pick(*keys):
    for k in keys:
        v = (data.get(k) or os.environ.get(k) or "").strip()
        if v:
            return v
    return ""

db = pick("DATABASE_URL", "CREW_DATABASE_URL")
aliases = {
    "CREW_DATABASE_URL": db,
    "DATABASE_URL": db,
    "SLACK_ADMIN_CHANNEL_ID": pick("SLACK_ADMIN_CHANNEL_ID", "SLACK_AGENT_DISCUSSION_CHANNEL_ID", "SLACK_DIGEST_CHANNEL_ID"),
    "LANGFUSE_HOST": pick("LANGFUSE_HOST", "LANGFUSE_BASE_URL") or "https://us.cloud.langfuse.com",
}
for k, v in aliases.items():
    if v:
        data[k] = v
        if k not in order:
            order.append(k)

# Never keep localhost DB on Droplet when production DATABASE_URL exists.
if on_droplet and db and "127.0.0.1" not in db and "localhost" not in db:
    for bad in ("CREW_DATABASE_URL", "DATABASE_URL"):
        if bad in data and ("127.0.0.1" in data[bad] or "localhost" in data[bad]):
            data[bad] = db

# FinOps: on Droplet, read compose logs locally (no SSH hop).
if on_droplet:
    data.pop("FINOPS_SSH_HOST", None)
    data.pop("FINOPS_SSH_USER", None)
    if not pick("FINOPS_LOG_COMMAND"):
        data["FINOPS_LOG_COMMAND"] = (
            "docker compose -f deploy/docker-compose.production.yml logs --since {lookback_hours}h api worker beat"
        )

out = []
seen = set()
for item in order:
    if item.startswith("#") or "=" in item:
        out.append(item)
        continue
    if item in seen:
        continue
    seen.add(item)
    if item in data:
        out.append(f"{item}={data[item]}")
for k, v in data.items():
    if k not in seen:
        out.append(f"{k}={v}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY

mv "$TMP" "$CREW_ENV"
trap - EXIT

if [[ "$ON_DROPLET" == "1" ]]; then
  echo "Updated ${CREW_ENV} from deploy/.env on Droplet (production source of truth)."
else
  echo "Updated ${CREW_ENV} (dev mirror from Droplet)."
fi

PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3
PARKINGLOT_RUNTIME=$([[ "$ON_DROPLET" == "1" ]] && echo droplet || echo local) \
  "$PY" - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path("${ROOT}") / "services" / "crew"))
from parking_crew.env import configured_secret_keys
from parking_crew.runtime import runtime_label
print(json.dumps({"runtime": runtime_label(), "configured": configured_secret_keys()}, indent=2))
PY
