# shellcheck shell=bash
# Resolve and verify Droplet target for this repo (source from deploy scripts).
# Prevents syncing parkinglot to the mobile-home-parks server (or vice versa).

_droplet_target_repo_root() {
  local script_dir="$1"
  cd "$(dirname "${script_dir}")/.." && pwd
}

_droplet_target_file() {
  echo "$(_droplet_target_repo_root "$1")/deploy/droplet.target"
}

# Load deploy/droplet.target into the environment (key=value, # comments allowed).
load_droplet_target() {
  local root script_dir target f key val
  script_dir="${1:?script_dir required}"
  root="$(_droplet_target_repo_root "$script_dir")"
  target="$root/deploy/droplet.target"
  if [[ ! -f "$target" ]]; then
    echo "error: missing $target — cannot verify which Droplet this repo uses." >&2
    return 1
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$line" ]] && continue
    [[ "$line" != *"="* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="$(echo "$key" | tr '[:upper:]' '[:lower:]')"
    case "$key" in
      project_id) DROPLET_PROJECT_ID="$val" ;;
      ssh_host) DROPLET_SSH_HOST="$val" ;;
      remote_path) DROPLET_REMOTE_PATH="$val" ;;
      allowed_hostname) DROPLET_ALLOWED_HOSTNAME="$val" ;;
      ssh_user) DROPLET_SSH_USER="$val" ;;
    esac
  done <"$target"
  export DROPLET_PROJECT_ID DROPLET_SSH_HOST DROPLET_REMOTE_PATH DROPLET_ALLOWED_HOSTNAME DROPLET_SSH_USER
  return 0
}

# Resolve SSH HostName for an alias or IP (ssh -G).
_droplet_resolve_hostname() {
  local host="$1"
  ssh -G "$host" 2>/dev/null | awk '/^hostname / { print $2; exit }'
}

# Apply droplet.target defaults; abort if caller overrides with wrong host/project.
assert_droplet_target() {
  local script_dir="${1:?}"
  local caller_droplet="${2:-}"
  local caller_remote="${3:-}"
  local caller_user="${4:-}"

  load_droplet_target "$script_dir" || return 1

  : "${DROPLET_PROJECT_ID:?droplet.target missing project_id}"
  : "${DROPLET_SSH_HOST:?droplet.target missing ssh_host}"
  : "${DROPLET_REMOTE_PATH:?droplet.target missing remote_path}"
  : "${DROPLET_ALLOWED_HOSTNAME:?droplet.target missing allowed_hostname}"

  local use_host use_path use_user resolved
  use_host="${caller_droplet:-$DROPLET_SSH_HOST}"
  use_path="${caller_remote:-$DROPLET_REMOTE_PATH}"
  use_user="${caller_user:-${DROPLET_SSH_USER:-cursor}}"

  resolved="$(_droplet_resolve_hostname "$use_host")"
  if [[ -z "$resolved" ]]; then
    echo "error: cannot resolve SSH host '$use_host' (check ~/.ssh/config)." >&2
    return 1
  fi

  if [[ "$resolved" != "$DROPLET_ALLOWED_HOSTNAME" ]]; then
    echo "" >&2
    echo "╔══════════════════════════════════════════════════════════════════╗" >&2
    echo "║  DROPLET MISMATCH — aborted to protect the wrong server         ║" >&2
    echo "╚══════════════════════════════════════════════════════════════════╝" >&2
    echo "  Repo project:     $DROPLET_PROJECT_ID" >&2
    echo "  Allowed IP:       $DROPLET_ALLOWED_HOSTNAME" >&2
    echo "  You aimed at:     $use_host → $resolved" >&2
    echo "  Remote path:      $use_path" >&2
    echo "" >&2
    echo "  Use ONLY:  DROPLET=$DROPLET_SSH_HOST  (or omit DROPLET — script uses deploy/droplet.target)" >&2
    echo "  SSH config:  ssh $DROPLET_SSH_HOST" >&2
    return 1
  fi

  if [[ -n "$caller_droplet" && "$caller_droplet" != "$DROPLET_SSH_HOST" && "$caller_droplet" != "$DROPLET_ALLOWED_HOSTNAME" ]]; then
    echo "warning: DROPLET=$caller_droplet differs from ssh_host=$DROPLET_SSH_HOST (IP matches; continuing)" >&2
  fi

  export DROPLET="$use_host"
  export REMOTE_PATH="$use_path"
  export SSH_USER="$use_user"

  echo "▶ Droplet target: project=$DROPLET_PROJECT_ID host=$use_host ($resolved) path=$use_path user=$use_user"

  if ! ssh -o BatchMode=yes -o ConnectTimeout=15 "${SSH_USER}@${DROPLET}" \
    "test -f '${REMOTE_PATH}/.droplet-project-id'" 2>/dev/null; then
    echo "warning: remote ${REMOTE_PATH}/.droplet-project-id missing — run scripts/install-droplet-project-marker.sh" >&2
    return 0
  fi

  local remote_id
  remote_id="$(ssh -o BatchMode=yes -o ConnectTimeout=15 "${SSH_USER}@${DROPLET}" \
    "cat '${REMOTE_PATH}/.droplet-project-id'" 2>/dev/null | tr -d '\r\n' || true)"
  if [[ -n "$remote_id" && "$remote_id" != "$DROPLET_PROJECT_ID" ]]; then
    echo "" >&2
    echo "╔══════════════════════════════════════════════════════════════════╗" >&2
    echo "║  REMOTE PROJECT MISMATCH — wrong directory on this Droplet      ║" >&2
    echo "╚══════════════════════════════════════════════════════════════════╝" >&2
    echo "  This repo expects:  $DROPLET_PROJECT_ID" >&2
    echo "  Remote path says:   $remote_id  ($REMOTE_PATH)" >&2
    return 1
  fi
  echo "  Remote marker OK:   .droplet-project-id=$remote_id"
  return 0
}
