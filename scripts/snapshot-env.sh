#!/usr/bin/env bash
set -euo pipefail

COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET_DIR="${WORKSPACE_DIR}/state/snapshots/${STAMP}"

mkdir -p "${TARGET_DIR}"
"${COMFY_VENV}/bin/pip" freeze > "${TARGET_DIR}/pip-freeze.txt"
cp /opt/bootstrap/base-requirements.lock "${TARGET_DIR}/base-requirements.lock"

echo "Saved environment snapshot to ${TARGET_DIR}"
