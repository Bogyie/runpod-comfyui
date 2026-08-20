#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${DOCKER_CONFIG_FILE:-docker.env}"
if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Missing Docker version config: ${CONFIG_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

required_vars=(
  IMAGE_NAME
  GITHUB_SHA
  GITHUB_OUTPUT
  BUILD_VARIANT
  PYTORCH_BASE_IMAGE
  COMFYUI_REF
  TRANSFORMERS_VERSION
  CADDY_VERSION
  CADDY_SECURITY_MODULE
  FILEBROWSER_VERSION
  RUNPODCTL_VERSION
  HUGGINGFACE_HUB_VERSION
  FILEBROWSER_LINUX_AMD64_SHA256
  RUNPODCTL_LINUX_AMD64_SHA256
  COMFYUI_MANAGER_REF
  KJNODES_REF
  RGTHREE_REF
  CRYSTOOLS_REF
)

for name in "${required_vars[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Required variable is empty: ${name}" >&2
    exit 1
  fi
done

case "${BUILD_VARIANT}" in
  basic)
    OPTIMIZATION_STAGE=optimized
    if [[ -z "${XFORMERS_VERSION:-}" || -z "${FLASH_ATTN_VERSION:-}" ]]; then
      echo "Optimized builds require XFORMERS_VERSION and FLASH_ATTN_VERSION" >&2
      exit 1
    fi
    ;;
  basic-unoptimized)
    OPTIMIZATION_STAGE=unoptimized
    ;;
  *)
    echo "Unsupported BUILD_VARIANT: ${BUILD_VARIANT}" >&2
    exit 1
    ;;
esac

hash_command() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$@"
  else
    shasum -a 256 "$@"
  fi
}

hash_payload() {
  hash_command | awk '{print substr($1, 1, 24)}'
}

hash_files() {
  for path in "$@"; do
    if [[ ! -f "${path}" ]]; then
      echo "Missing hash input file: ${path}" >&2
      exit 1
    fi
    printf 'file:%s\n' "${path}"
    hash_command "${path}"
  done
}

hash_tree() {
  local root="$1"
  if [[ ! -d "${root}" ]]; then
    echo "Missing hash input directory: ${root}" >&2
    exit 1
  fi
  find "${root}" -type f -print \
    | sort \
    | while read -r path; do
        printf 'file:%s\n' "${path}"
        hash_command "${path}"
      done
}

IMAGE_NAME_LC="$(printf '%s' "${IMAGE_NAME}" | tr '[:upper:]' '[:lower:]')"
BASE_TAG="${PYTORCH_BASE_IMAGE#pytorch/pytorch:}"
BASE_SLUG="$(printf '%s' "${BASE_TAG}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
COMFYUI_SLUG="$(printf '%s' "${COMFYUI_REF#v}" | tr -cd '[:alnum:]')"
VERSION_SLUG="${BASE_SLUG}-cf${COMFYUI_SLUG}"
SHORT_SHA="${GITHUB_SHA::7}"

COMMON_KEY="$(
  {
    printf 'base_image=%s\n' "${PYTORCH_BASE_IMAGE}"
    printf 'comfyui_ref=%s\n' "${COMFYUI_REF}"
    printf 'transformers_version=%s\n' "${TRANSFORMERS_VERSION}"
    printf 'caddy_version=%s\n' "${CADDY_VERSION}"
    printf 'caddy_security_module=%s\n' "${CADDY_SECURITY_MODULE}"
    printf 'filebrowser_version=%s\n' "${FILEBROWSER_VERSION}"
    printf 'runpodctl_version=%s\n' "${RUNPODCTL_VERSION}"
    printf 'huggingface_hub_version=%s\n' "${HUGGINGFACE_HUB_VERSION}"
    printf 'filebrowser_linux_amd64_sha256=%s\n' "${FILEBROWSER_LINUX_AMD64_SHA256}"
    printf 'runpodctl_linux_amd64_sha256=%s\n' "${RUNPODCTL_LINUX_AMD64_SHA256}"
    printf 'comfyui_manager_ref=%s\n' "${COMFYUI_MANAGER_REF}"
    printf 'kjnodes_ref=%s\n' "${KJNODES_REF}"
    printf 'rgthree_ref=%s\n' "${RGTHREE_REF}"
    printf 'crystools_ref=%s\n' "${CRYSTOOLS_REF}"
    hash_files .dockerignore docker/Dockerfile.basic start.sh
    hash_tree scripts
    hash_tree rootfs
  } | hash_payload
)"

VARIANT_KEY="$(
  {
    printf 'common_key=%s\n' "${COMMON_KEY}"
    printf 'variant=%s\n' "${BUILD_VARIANT}"
    printf 'optimization_stage=%s\n' "${OPTIMIZATION_STAGE}"
    if [[ "${OPTIMIZATION_STAGE}" == optimized ]]; then
      printf 'xformers_version=%s\n' "${XFORMERS_VERSION}"
      printf 'flash_attn_version=%s\n' "${FLASH_ATTN_VERSION}"
    fi
  } | hash_payload
)"

{
  echo "image_name_lc=${IMAGE_NAME_LC}"
  echo "version_slug=${VERSION_SLUG}"
  echo "short_sha=${SHORT_SHA}"
  echo "variant=${BUILD_VARIANT}"
  echo "optimization_stage=${OPTIMIZATION_STAGE}"
  echo "sha_image=${IMAGE_NAME_LC}:sha-${SHORT_SHA}-${BUILD_VARIANT}"
  echo "build_image=${IMAGE_NAME_LC}:buildkey-${BUILD_VARIANT}-${VARIANT_KEY}"
  echo "stable_image=${IMAGE_NAME_LC}:${BUILD_VARIANT}"
  echo "version_image=${IMAGE_NAME_LC}:${VERSION_SLUG}-${BUILD_VARIANT}"
} >> "${GITHUB_OUTPUT}"
