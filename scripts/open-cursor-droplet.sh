#!/usr/bin/env bash
# Open parkinglot on the production Droplet in Cursor (Remote SSH).
# Prefer this over "Open Folder" on the Mac clone — local shows "main · local".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${ROOT}/parkinglot-droplet.code-workspace"

if ! command -v cursor >/dev/null 2>&1; then
  echo "cursor CLI not found. Install: Cursor → Command Palette → Shell Command: Install 'cursor' command" >&2
  exit 1
fi

exec cursor "${WORKSPACE}"
