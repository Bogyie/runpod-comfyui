#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: enable-node.sh <node-directory-name>" >&2
  exit 1
fi

STORAGE_DIR="${STORAGE_DIR:-/workspace/storage}"
NODE_NAME="$1"
SRC="${STORAGE_DIR}/custom_nodes.disabled/${NODE_NAME}"
DST="${STORAGE_DIR}/custom_nodes/${NODE_NAME}"

if [[ ! -e "${SRC}" ]]; then
  echo "Disabled node not found: ${SRC}" >&2
  exit 1
fi

mv "${SRC}" "${DST}"
echo "Enabled ${NODE_NAME}"
