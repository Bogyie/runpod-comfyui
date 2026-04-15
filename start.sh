#!/usr/bin/env bash
set -euo pipefail

export COMFY_HOME="${COMFY_HOME:-/opt/comfy}"
export COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
export COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
export WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
export STORAGE_DIR="${STORAGE_DIR:-/workspace/storage}"
export COMFYUI_PORT="${COMFYUI_PORT:-8188}"
export CODE_SERVER_PORT="${CODE_SERVER_PORT:-8080}"
export COMFYUI_HOST="${COMFYUI_HOST:-0.0.0.0}"
export CODE_SERVER_HOST="${CODE_SERVER_HOST:-0.0.0.0}"
export CODE_SERVER_AUTH="${CODE_SERVER_AUTH:-none}"
export CLI_ARGS="${CLI_ARGS:-}"
if [[ -n "${RUNPOD_POD_ID:-}" ]]; then
  export COMFY_ORIGIN="https://${RUNPOD_POD_ID}-${COMFYUI_PORT}.proxy.runpod.net"
else
  export COMFY_ORIGIN="http://localhost:${COMFYUI_PORT}"
fi

log() {
  printf '[startup] %s\n' "$*"
}

cleanup() {
  local exit_code=$?
  log "Shutting down background services..."
  jobs -pr | xargs -r kill 2>/dev/null || true
  exit ${exit_code}
}

trap cleanup EXIT INT TERM

log "Initializing workspace layout..."
/opt/bootstrap/scripts/init-storage.sh

mkdir -p "${WORKSPACE_DIR}/logs" "${WORKSPACE_DIR}/code-server"

if [[ ! -f "${WORKSPACE_DIR}/code-server/config.yaml" ]]; then
  cat > "${WORKSPACE_DIR}/code-server/config.yaml" <<EOF
bind-addr: ${CODE_SERVER_HOST}:${CODE_SERVER_PORT}
auth: ${CODE_SERVER_AUTH}
cert: false
app-name: Runpod ComfyUI
user-data-dir: ${WORKSPACE_DIR}/code-server/user-data
extensions-dir: ${WORKSPACE_DIR}/code-server/extensions
EOF
fi

log "Starting code-server on port ${CODE_SERVER_PORT}..."
code-server \
  --config "${WORKSPACE_DIR}/code-server/config.yaml" \
  "${WORKSPACE_DIR}" \
  > "${WORKSPACE_DIR}/logs/code-server.log" 2>&1 &
CODE_PID=$!

source "${COMFY_VENV}/bin/activate"

read -ra cli_args <<< "${CLI_ARGS}"

log "Starting ComfyUI on port ${COMFYUI_PORT}..."
python "${COMFYUI_DIR}/main.py" \
  --listen "${COMFYUI_HOST}" \
  --port "${COMFYUI_PORT}" \
  --enable-cors-header "${COMFY_ORIGIN}" \
  "${cli_args[@]+"${cli_args[@]}"}" \
  > "${WORKSPACE_DIR}/logs/comfyui.log" 2>&1 &
COMFY_PID=$!

log "ComfyUI log: ${WORKSPACE_DIR}/logs/comfyui.log"
log "code-server log: ${WORKSPACE_DIR}/logs/code-server.log"
log "Waiting for services..."

wait -n ${CODE_PID} ${COMFY_PID} || true
EXIT_CODE=$?

if ! kill -0 ${CODE_PID} 2>/dev/null; then
  log "code-server (PID ${CODE_PID}) exited with code ${EXIT_CODE}, shutting down"
  exit ${EXIT_CODE}
fi

log "ComfyUI (PID ${COMFY_PID}) exited with code ${EXIT_CODE}"
log "code-server is still running — use restart-comfyui.sh to recover:"
log "  /opt/bootstrap/scripts/restart-comfyui.sh           # restart only"
log "  /opt/bootstrap/scripts/restart-comfyui.sh --recover  # restore env + restart"

wait ${CODE_PID} || true
