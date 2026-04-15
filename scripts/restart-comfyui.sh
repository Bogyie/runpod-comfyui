#!/usr/bin/env bash
set -euo pipefail

COMFY_HOME="${COMFY_HOME:-/opt/comfy}"
COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
COMFYUI_HOST="${COMFYUI_HOST:-0.0.0.0}"
CLI_ARGS="${CLI_ARGS:-}"

if [[ -n "${RUNPOD_POD_ID:-}" ]]; then
  COMFY_ORIGIN="https://${RUNPOD_POD_ID}-${COMFYUI_PORT}.proxy.runpod.net"
else
  COMFY_ORIGIN="http://localhost:${COMFYUI_PORT}"
fi

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
pkill -f "python.*main.py" 2>/dev/null || true
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

source "${COMFY_VENV}/bin/activate"
read -ra cli_args <<< "${CLI_ARGS}"

echo "Starting ComfyUI on port ${COMFYUI_PORT}..."
python "${COMFYUI_DIR}/main.py" \
  --listen "${COMFYUI_HOST}" \
  --port "${COMFYUI_PORT}" \
  --enable-cors-header "${COMFY_ORIGIN}" \
  "${cli_args[@]+"${cli_args[@]}"}" \
  >> "${WORKSPACE_DIR}/logs/comfyui.log" 2>&1 &
COMFY_PID=$!

echo "ComfyUI restarted (PID ${COMFY_PID})"
echo "Log: ${WORKSPACE_DIR}/logs/comfyui.log"
echo "Tail log: tail -f ${WORKSPACE_DIR}/logs/comfyui.log"
