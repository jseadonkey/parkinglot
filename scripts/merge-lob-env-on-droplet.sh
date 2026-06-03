#!/usr/bin/env bash
# Merge LOB_* + OUTREACH_SENDER_* into remote deploy/.env (called from Deploy to Droplet).
# Requires LOB_API_KEY in the environment (GitHub Actions secret).
set -euo pipefail

REMOTE_PATH="${1:?remote path}"
LOB_API_KEY="${LOB_API_KEY:?LOB_API_KEY required}"

ssh -oBatchMode=yes "${DROPLET_USER}@${DROPLET_HOST}" \
  REMOTE_PATH="$(printf '%q' "$REMOTE_PATH")" \
  ENC_LOB_API_KEY="$(printf '%s' "$LOB_API_KEY" | base64 | tr -d '\n')" \
  bash -s <<'EOS'
set -euo pipefail
cd "$REMOTE_PATH"
test -f deploy/.env

LOB_API_KEY="$(printf '%s' "$ENC_LOB_API_KEY" | base64 -d)"
export LOB_API_KEY

python3 <<'PY'
import os
import pathlib

env_path = pathlib.Path("deploy") / ".env"
text = env_path.read_text(encoding="utf-8")
prefixes = ("LOB_", "OUTREACH_SENDER_")
lines = [ln for ln in text.splitlines() if not any(ln.startswith(p) for p in prefixes)]
body = "\n".join(lines).rstrip() + "\n"
values = {
    "LOB_API_KEY": os.environ["LOB_API_KEY"],
    "LOB_SEND_ENABLED": "false",
    "LOB_FROM_NAME": "vspecialist.com",
    "LOB_FROM_ADDRESS_LINE1": "1810 E Sahara Ave",
    "LOB_FROM_ADDRESS_LINE2": "STE 75609",
    "LOB_FROM_ADDRESS_CITY": "Las Vegas",
    "LOB_FROM_ADDRESS_STATE": "NV",
    "LOB_FROM_ADDRESS_ZIP": "89104",
    "LOB_MAIL_EXTRA_SERVICE": "certified",
    "OUTREACH_SENDER_COMPANY": "vspecialist.com",
    "OUTREACH_SENDER_EMAIL": "parking@johndemayo.com",
}
addition_lines = ["# Lob — merged by scripts/merge-lob-env-on-droplet.sh (Deploy to Droplet)"]
for key, val in values.items():
    addition_lines.append(f"{key}={val}")
env_path.write_text(body + "\n".join(addition_lines) + "\n", encoding="utf-8", newline="\n")
print("Updated", env_path, "with LOB_* entries.")
PY
EOS
