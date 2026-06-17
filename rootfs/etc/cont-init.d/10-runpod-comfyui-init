#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[runpod-init] %s\n' "$*"
}

export COMFY_HOME="${COMFY_HOME:-/opt/comfy}"
export COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
export COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
export WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
export STORAGE_DIR="${STORAGE_DIR:-/workspace/storage}"
export COMFYUI_PORT="${COMFYUI_PORT:-8188}"
export COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
export FILEBROWSER_PORT="${FILEBROWSER_PORT:-8080}"
export FILEBROWSER_HOST="${FILEBROWSER_HOST:-127.0.0.1}"
export FILEBROWSER_BASEURL="${FILEBROWSER_BASEURL:-/files}"
export CADDY_HTTPS_PORT="${CADDY_HTTPS_PORT:-8443}"
export CADDY_BASIC_AUTH_USER="${CADDY_BASIC_AUTH_USER:-runpod}"
export CADDY_BASIC_AUTH_PASSWORD="${CADDY_BASIC_AUTH_PASSWORD:-runpod-comfyui}"
export CADDY_CONFIG_DIR="${CADDY_CONFIG_DIR:-/etc/caddy}"
export CADDY_DATA_DIR="${CADDY_DATA_DIR:-${STORAGE_DIR}/caddy}"
export CADDY_TLS_DIR="${CADDY_TLS_DIR:-${CADDY_DATA_DIR}/tls}"
export CADDY_TLS_COMMON_NAME="${CADDY_TLS_COMMON_NAME:-runpod-comfyui.local}"
export CADDY_TLS_DAYS="${CADDY_TLS_DAYS:-3650}"

case "${CADDY_BASIC_AUTH_USER}" in
  *[!A-Za-z0-9._-]*|'')
    log "CADDY_BASIC_AUTH_USER must contain only A-Z, a-z, 0-9, dot, underscore, or dash"
    exit 1
    ;;
esac

log "Initializing workspace layout"
/opt/bootstrap/scripts/init-storage.sh

mkdir -p \
  "${WORKSPACE_DIR}/logs" \
  "${STORAGE_DIR}/filebrowser" \
  "${CADDY_CONFIG_DIR}" \
  "${CADDY_DATA_DIR}" \
  "${CADDY_TLS_DIR}"

if [[ "${CADDY_TLS_REGENERATE:-false}" == "true" ]] || \
   [[ ! -s "${CADDY_TLS_DIR}/tls.crt" ]] || \
   [[ ! -s "${CADDY_TLS_DIR}/tls.key" ]]; then
  log "Generating self-signed Caddy TLS certificate"
  rm -f "${CADDY_TLS_DIR}/tls.crt" "${CADDY_TLS_DIR}/tls.key"
  openssl req \
    -x509 \
    -newkey rsa:2048 \
    -sha256 \
    -nodes \
    -days "${CADDY_TLS_DAYS}" \
    -keyout "${CADDY_TLS_DIR}/tls.key" \
    -out "${CADDY_TLS_DIR}/tls.crt" \
    -subj "/CN=${CADDY_TLS_COMMON_NAME}" \
    -addext "subjectAltName=DNS:${CADDY_TLS_COMMON_NAME},IP:127.0.0.1"
fi

chmod 600 "${CADDY_TLS_DIR}/tls.key"
chmod 644 "${CADDY_TLS_DIR}/tls.crt"

if [[ -n "${CADDY_BASIC_AUTH_HASH:-}" ]]; then
  auth_hash="${CADDY_BASIC_AUTH_HASH}"
else
  auth_hash="$(caddy hash-password --plaintext "${CADDY_BASIC_AUTH_PASSWORD}")"
fi

cat > "${CADDY_CONFIG_DIR}/Caddyfile" <<EOF
{
	admin off
	auto_https disable_redirects
	storage file_system ${CADDY_DATA_DIR}
	servers {
		protocols h1 h2
	}
}

:${CADDY_HTTPS_PORT} {
	tls ${CADDY_TLS_DIR}/tls.crt ${CADDY_TLS_DIR}/tls.key
	encode zstd gzip

	log {
		output file ${WORKSPACE_DIR}/logs/caddy-access.log
	}

	basic_auth {
		${CADDY_BASIC_AUTH_USER} ${auth_hash}
	}

	@filebrowser path ${FILEBROWSER_BASEURL} ${FILEBROWSER_BASEURL}/*
	handle @filebrowser {
		reverse_proxy ${FILEBROWSER_HOST}:${FILEBROWSER_PORT}
	}

	handle {
		reverse_proxy ${COMFYUI_HOST}:${COMFYUI_PORT}
	}
}
EOF

log "Caddy will listen on ${CADDY_HTTPS_PORT}; ComfyUI and File Browser stay on localhost"
