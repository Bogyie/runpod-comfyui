#!/usr/bin/env bash
set -euo pipefail

COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
LOCK_FILE="${1:-/opt/bootstrap/base-requirements.lock}"

if [[ ! -f "${LOCK_FILE}" ]]; then
  echo "Lock file not found: ${LOCK_FILE}" >&2
  exit 1
fi

"${COMFY_VENV}/bin/pip" install --upgrade pip wheel setuptools
if compgen -G "/opt/wheels/*.whl" > /dev/null; then
  "${COMFY_VENV}/bin/pip" install --no-index --find-links /opt/wheels -r "${LOCK_FILE}"
else
  "${COMFY_VENV}/bin/pip" install -r "${LOCK_FILE}"
fi

echo "Restored environment from ${LOCK_FILE}"
