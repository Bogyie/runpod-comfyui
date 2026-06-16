#!/usr/bin/env bash
set -euo pipefail

COMFY_HOME="${COMFY_HOME:-/opt/comfy}"
COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"

rm -rf \
  /root/.cache \
  /tmp/* \
  /var/tmp/* \
  /var/lib/apt/lists/*

if [[ -d "${COMFY_HOME}" ]]; then
  find "${COMFY_HOME}" -type d -name ".git" -prune -exec rm -rf {} +
  find "${COMFY_HOME}" -type d -name "__pycache__" -prune -exec rm -rf {} +
  find "${COMFY_HOME}" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
fi

if [[ -d "${COMFYUI_DIR}/custom_nodes" ]]; then
  find "${COMFYUI_DIR}/custom_nodes" -maxdepth 2 -type d \
    \( -name ".github" -o -name "docs" -o -name "tests" -o -name "test" \) \
    -prune -exec rm -rf {} +
fi
