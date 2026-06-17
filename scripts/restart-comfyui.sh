#!/usr/bin/env bash
set -euo pipefail

COMFY_HOME="${COMFY_HOME:-/opt/comfy}"
COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
COMFYUI_CORS_ORIGIN="${COMFYUI_CORS_ORIGIN:-*}"
CLI_ARGS="${CLI_ARGS:-}"

RECOVER=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recover)
      RECOVER=true
      shift
      ;;
    -h|--help)
      echo "Usage: restart-comfyui.sh [--recover]"
      echo ""
      echo "  --recover  Restore base environment before restarting"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: restart-comfyui.sh [--recover]" >&2
      exit 1
      ;;
  esac
done

echo "Stopping existing ComfyUI process..."
if command -v s6-svc >/dev/null 2>&1 && [[ -d /run/service/comfyui ]]; then
  s6-svc -d /run/service/comfyui
else
  pkill -f "python.*main.py" 2>/dev/null || true
fi
sleep 2

if ${RECOVER}; then
  echo "Restoring base environment..."
  /opt/bootstrap/scripts/restore-env.sh
fi

if [[ -f /opt/bootstrap/protected-package-manifest.json ]]; then
  echo "Verifying protected packages..."
  "${COMFY_VENV}/bin/python" /opt/bootstrap/scripts/verify_protected_packages.py \
    verify \
    /opt/bootstrap/protected-package-manifest.json
fi

# shellcheck source=/dev/null
source "${COMFY_VENV}/bin/activate"
read -ra cli_args <<< "${CLI_ARGS}"

echo "Starting ComfyUI on port ${COMFYUI_PORT}..."
if command -v s6-svc >/dev/null 2>&1 && [[ -d /run/service/comfyui ]]; then
  s6-svc -u /run/service/comfyui
  echo "ComfyUI service restarted"
else
  command=(
    python "${COMFYUI_DIR}/main.py"
    --listen "${COMFYUI_HOST}"
    --port "${COMFYUI_PORT}"
  )

  if [[ -n "${COMFYUI_CORS_ORIGIN}" ]]; then
    command+=(--enable-cors-header "${COMFYUI_CORS_ORIGIN}")
  fi

  command+=("${cli_args[@]+"${cli_args[@]}"}")
  "${command[@]}" >> "${WORKSPACE_DIR}/logs/comfyui.log" 2>&1 &
  COMFY_PID=$!
  echo "ComfyUI restarted (PID ${COMFY_PID})"
fi

echo "Log: ${WORKSPACE_DIR}/logs/comfyui.log"
echo "Tail log: tail -f ${WORKSPACE_DIR}/logs/comfyui.log"
