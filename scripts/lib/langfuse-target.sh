#!/usr/bin/env bash
# Source hardwired Langfuse US URL (config/langfuse.env).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/config/langfuse.env"
