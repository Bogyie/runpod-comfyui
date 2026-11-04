#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[runpod-entrypoint] %s\n' "$*"
}

if (( "$#" > 0 )); then
  log "Running custom command: $*"
  exec "$@"
fi

export WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
mkdir -p "${WORKSPACE_DIR}/logs"

log "Initializing runtime"
/opt/bootstrap/scripts/runpod-runtime-init.sh

log "Starting supervisord"
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
