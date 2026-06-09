#!/usr/bin/env bash
# Install parking-crew into repo .venv and run pytest (no LLM / Slack / GitHub required).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UV="${ROOT}/.uv-bin/uv"
if [[ ! -x "$UV" ]]; then
  echo "Installing uv to ${ROOT}/.uv-bin ..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="${ROOT}/.uv-bin" INSTALLER_NO_MODIFY_PATH=1 sh
fi
"$UV" python install 3.12 >/dev/null
if [[ ! -x "${ROOT}/.venv/bin/python" ]]; then
  "$UV" venv --python 3.12 "${ROOT}/.venv"
fi
"$UV" pip install -p "${ROOT}/.venv/bin/python" --upgrade pip >/dev/null
"$UV" pip install -p "${ROOT}/.venv/bin/python" "./services/crew[dev]" >/dev/null

#!/usr/bin/env bash
# Install parking-crew into repo .venv and run pytest (no LLM / Slack / GitHub required).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UV="${ROOT}/.uv-bin/uv"
if [[ ! -x "$UV" ]]; then
  echo "Installing uv to ${ROOT}/.uv-bin ..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="${ROOT}/.uv-bin" INSTALLER_NO_MODIFY_PATH=1 sh
fi
"$UV" python install 3.12 >/dev/null
if [[ ! -x "${ROOT}/.venv/bin/python" ]]; then
  "$UV" venv --python 3.12 "${ROOT}/.venv"
fi
"$UV" pip install -p "${ROOT}/.venv/bin/python" --upgrade pip >/dev/null
"$UV" pip install -p "${ROOT}/.venv/bin/python" "./services/crew[dev]" >/dev/null

echo "==> pytest services/crew/tests" >&2
"${ROOT}/.venv/bin/python" -m pytest "${ROOT}/services/crew/tests" -q
