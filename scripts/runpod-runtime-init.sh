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
export FILEBROWSER_PROXY_HEADER="${FILEBROWSER_PROXY_HEADER:-X-AuthCrunch-User}"
export CADDY_HTTPS_PORT="${CADDY_HTTPS_PORT:-8443}"
runpod_tcp_port_var="RUNPOD_TCP_PORT_${CADDY_HTTPS_PORT}"
export CADDY_PUBLIC_PORT="${CADDY_PUBLIC_PORT:-${!runpod_tcp_port_var:-${CADDY_HTTPS_PORT}}}"
if [[ -n "${RUNPOD_PUBLIC_IP:-}" ]]; then
  export CADDY_PUBLIC_URL="${CADDY_PUBLIC_URL:-https://${RUNPOD_PUBLIC_IP}:${CADDY_PUBLIC_PORT}}"
else
  export CADDY_PUBLIC_URL="${CADDY_PUBLIC_URL:-}"
fi
export CADDY_TLS_SERVER_NAME="${CADDY_TLS_SERVER_NAME:-${RUNPOD_PUBLIC_IP:-runpod-comfyui.local}}"
export CADDY_CONFIG_DIR="${CADDY_CONFIG_DIR:-/etc/caddy}"
export CADDY_DATA_DIR="${CADDY_DATA_DIR:-${STORAGE_DIR}/caddy}"
export AUTHCRUNCH_AUTH_PATH="${AUTHCRUNCH_AUTH_PATH:-/auth}"
export AUTHCRUNCH_USERS_FILE="${AUTHCRUNCH_USERS_FILE:-${CADDY_DATA_DIR}/authcrunch/users.json}"
export AUTHCRUNCH_JWT_KEY_FILE="${AUTHCRUNCH_JWT_KEY_FILE:-${CADDY_DATA_DIR}/authcrunch/jwt_shared_key}"
export AUTHP_ADMIN_USER="${AUTHP_ADMIN_USER:-${AUTHCRUNCH_ADMIN_USER:-runpod}}"
export AUTHP_ADMIN_EMAIL="${AUTHP_ADMIN_EMAIL:-${AUTHCRUNCH_ADMIN_EMAIL:-runpod@localdomain.local}}"
export AUTHP_ADMIN_SECRET="${AUTHP_ADMIN_SECRET:-${AUTHCRUNCH_ADMIN_PASSWORD:-runpod-comfyui}}"

case "${AUTHCRUNCH_AUTH_PATH}" in
  /*) ;;
  *)
    log "AUTHCRUNCH_AUTH_PATH must start with /"
    exit 1
    ;;
esac

AUTHCRUNCH_AUTH_PATH="${AUTHCRUNCH_AUTH_PATH%/}"
if [[ -z "${AUTHCRUNCH_AUTH_PATH}" || "${AUTHCRUNCH_AUTH_PATH}" == "/" ]]; then
  log "AUTHCRUNCH_AUTH_PATH must not be /"
  exit 1
fi

log "Initializing workspace layout"
/opt/bootstrap/scripts/init-storage.sh

mkdir -p \
  "${WORKSPACE_DIR}/logs" \
  "${STORAGE_DIR}/filebrowser" \
  "${CADDY_CONFIG_DIR}" \
  "${CADDY_DATA_DIR}" \
  "$(dirname "${AUTHCRUNCH_USERS_FILE}")" \
  "$(dirname "${AUTHCRUNCH_JWT_KEY_FILE}")"

if [[ -n "${AUTHCRUNCH_JWT_SHARED_KEY:-}" ]]; then
  jwt_shared_key="${AUTHCRUNCH_JWT_SHARED_KEY}"
elif [[ -n "${JWT_SHARED_KEY:-}" ]]; then
  jwt_shared_key="${JWT_SHARED_KEY}"
else
  if [[ ! -s "${AUTHCRUNCH_JWT_KEY_FILE}" ]]; then
    log "Generating persistent AuthCrunch JWT shared key"
    "${COMFY_VENV}/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))' > "${AUTHCRUNCH_JWT_KEY_FILE}"
    chmod 600 "${AUTHCRUNCH_JWT_KEY_FILE}"
  fi
  jwt_shared_key="$(<"${AUTHCRUNCH_JWT_KEY_FILE}")"
fi

{
  printf 'export AUTHP_ADMIN_USER=%q\n' "${AUTHP_ADMIN_USER}"
  printf 'export AUTHP_ADMIN_EMAIL=%q\n' "${AUTHP_ADMIN_EMAIL}"
  printf 'export AUTHP_ADMIN_SECRET=%q\n' "${AUTHP_ADMIN_SECRET}"
  printf 'export JWT_SHARED_KEY=%q\n' "${jwt_shared_key}"
} > "${CADDY_CONFIG_DIR}/authcrunch.env"
chmod 600 "${CADDY_CONFIG_DIR}/authcrunch.env"

cat > "${CADDY_CONFIG_DIR}/Caddyfile" <<EOF
{
	admin off
	auto_https disable_redirects
	storage file_system ${CADDY_DATA_DIR}
	default_sni ${CADDY_TLS_SERVER_NAME}
	fallback_sni ${CADDY_TLS_SERVER_NAME}
	order authenticate before respond
	order authorize before reverse_proxy
	servers {
		protocols h1 h2
	}

	security {
		local identity store localdb {
			realm local
			path ${AUTHCRUNCH_USERS_FILE}
			user {env.AUTHP_ADMIN_USER} {
				email {env.AUTHP_ADMIN_EMAIL}
				password {env.AUTHP_ADMIN_SECRET} overwrite
				roles "authp/admin" "authp/user"
			}
		}

		authentication portal runpod_portal {
			crypto default token lifetime 86400
			crypto key sign-verify {env.JWT_SHARED_KEY}
			enable identity store localdb
			cookie guess domain
			ui {
				links {
					"ComfyUI" / icon "las la-project-diagram"
					"File Browser" ${FILEBROWSER_BASEURL}/ icon "las la-folder"
				}
			}
			transform user {
				match origin local
				action add role authp/user
			}
		}

		authorization policy runpod_policy {
			set auth url ${AUTHCRUNCH_AUTH_PATH}/
			crypto key verify {env.JWT_SHARED_KEY}
			allow roles authp/admin authp/user
		}
	}
}

${CADDY_TLS_SERVER_NAME}:${CADDY_HTTPS_PORT}, :${CADDY_HTTPS_PORT} {
	tls internal
	encode zstd gzip

	log {
		output file ${WORKSPACE_DIR}/logs/caddy-access.log
	}

	handle ${AUTHCRUNCH_AUTH_PATH}* {
		authenticate * with runpod_portal
	}

	@filebrowser path ${FILEBROWSER_BASEURL} ${FILEBROWSER_BASEURL}/*
	handle @filebrowser {
		authorize with runpod_policy
		reverse_proxy ${FILEBROWSER_HOST}:${FILEBROWSER_PORT} {
			header_up ${FILEBROWSER_PROXY_HEADER} {http.auth.user.id}
			header_up X-AuthCrunch-Realm {http.auth.user.realm}
		}
	}

	handle {
		authorize with runpod_policy
		reverse_proxy ${COMFYUI_HOST}:${COMFYUI_PORT}
	}
}
EOF

if [[ -n "${CADDY_PUBLIC_URL}" ]]; then
  log "Caddy will listen on internal port ${CADDY_HTTPS_PORT}; RunPod public URL is ${CADDY_PUBLIC_URL}"
elif [[ "${CADDY_PUBLIC_PORT}" != "${CADDY_HTTPS_PORT}" ]]; then
  log "Caddy will listen on internal port ${CADDY_HTTPS_PORT}; RunPod mapped public TCP port is ${CADDY_PUBLIC_PORT}"
else
  log "Caddy will listen on internal port ${CADDY_HTTPS_PORT}"
fi
log "Caddy TLS server name is ${CADDY_TLS_SERVER_NAME}"
log "AuthCrunch is mounted at ${AUTHCRUNCH_AUTH_PATH}; ComfyUI and File Browser stay on localhost"
