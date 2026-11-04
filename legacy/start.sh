#!/usr/bin/env bash
set -euo pipefail

export COMFY_HOME="${COMFY_HOME:-/opt/comfy}"
export COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
export COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
export WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
export STORAGE_DIR="${STORAGE_DIR:-/workspace/storage}"
export COMFYUI_PORT="${COMFYUI_PORT:-8188}"
export COMFYUI_HOST="${COMFYUI_HOST:-0.0.0.0}"
export CLI_ARGS="${CLI_ARGS:-}"
export COMFYUI_CORS_ORIGIN="${COMFYUI_CORS_ORIGIN:-*}"

log() {
  printf '[startup] %s\n' "$*"
}

log "Initializing workspace layout..."
/opt/bootstrap/scripts/init-storage.sh

mkdir -p "${WORKSPACE_DIR}/logs"

# shellcheck source=/dev/null
source "${COMFY_VENV}/bin/activate"
read -ra cli_args <<< "${CLI_ARGS}"

log "Starting ComfyUI on port ${COMFYUI_PORT}..."
command=(
  python "${COMFYUI_DIR}/main.py" \
  --listen "${COMFYUI_HOST}" \
  --port "${COMFYUI_PORT}"
)

if [[ -n "${COMFYUI_CORS_ORIGIN}" ]]; then
  command+=(--enable-cors-header "${COMFYUI_CORS_ORIGIN}")
fi

command+=("${cli_args[@]+"${cli_args[@]}"}")

exec >> "${WORKSPACE_DIR}/logs/comfyui.log" 2>&1
exec "${command[@]}"
