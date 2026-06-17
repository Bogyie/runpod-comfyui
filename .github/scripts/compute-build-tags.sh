#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME_LC="$(printf '%s' "${IMAGE_NAME}" | tr '[:upper:]' '[:lower:]')"
BASE_TAG="${PYTORCH_BASE_IMAGE#pytorch/pytorch:}"
BASE_SLUG="$(printf '%s' "${BASE_TAG}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
V_CF="${COMFYUI_VERSION//./}"
VERSION_SLUG="${BASE_SLUG}-cf${V_CF}"
SHORT_SHA="${GITHUB_SHA::7}"

hash_payload() {
  sha256sum | cut -d' ' -f1 | cut -c1-24
}

hash_files() {
  for path in "$@"; do
    if [[ ! -f "${path}" ]]; then
      echo "Missing hash input file: ${path}" >&2
      exit 1
    fi
    printf 'file:%s\n' "${path}"
    sha256sum "${path}"
  done
}

hash_tree() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "Missing hash input directory: ${path}" >&2
    exit 1
  fi
  find "${path}" -type f -print \
    | sort \
      | while read -r path; do
        printf 'file:%s\n' "${path}"
        sha256sum "${path}"
      done
}

hash_inputs() {
  hash_files "$@" \
    | sha256sum \
    | cut -d' ' -f1
}

hash_tree_inputs() {
  hash_tree "$1" \
    | sha256sum \
    | cut -d' ' -f1
}

COMFYUI_SCRIPT_HASH="$(hash_inputs \
  scripts/cleanup-image.sh \
  scripts/init-storage.sh \
  scripts/verify_image.py \
  scripts/verify_protected_packages.py)"

OPTIMIZED_SCRIPT_HASH="$(hash_inputs \
  scripts/cleanup-image.sh \
  scripts/resolve_flash_attn_wheel.py \
  scripts/torch_cuda_wheel_tag.py \
  scripts/verify_image.py \
  scripts/verify_protected_packages.py)"

RUNTIME_SCRIPT_HASH="$(hash_tree_inputs scripts)"

CUSTOM_INSTALL_SCRIPT_HASH="$(hash_inputs \
  scripts/cleanup-image.sh \
  scripts/install_custom_nodes.sh \
  scripts/verify_protected_packages.py)"

ROOTFS_HASH="$(hash_tree_inputs rootfs)"

COMFYUI_KEY="$(
  {
    printf 'stage=comfyui\n'
    printf 'base_image=%s\n' "${PYTORCH_BASE_IMAGE}"
    printf 'comfyui_ref=v%s\n' "${COMFYUI_VERSION}"
    printf 'transformers_version=%s\n' "${TRANSFORMERS_VERSION}"
    printf 'comfyui_script_hash=%s\n' "${COMFYUI_SCRIPT_HASH}"
    hash_files .dockerignore docker/Dockerfile.comfyui start.sh
  } | hash_payload
)"

OPTIMIZED_KEY="$(
  {
    printf 'stage=optimized\n'
    printf 'parent_key=%s\n' "${COMFYUI_KEY}"
    printf 'xformers_version=%s\n' "${XFORMERS_VERSION}"
    printf 'flash_attn_version=%s\n' "${FLASH_ATTN_VERSION}"
    printf 'optimized_script_hash=%s\n' "${OPTIMIZED_SCRIPT_HASH}"
    hash_files .dockerignore docker/Dockerfile.optimized
  } | hash_payload
)"

TOOLS_KEY="$(
  {
    printf 'stage=runtime-tools\n'
    printf 'parent_key=%s\n' "${OPTIMIZED_KEY}"
    printf 'caddy_version=%s\n' "${CADDY_VERSION}"
    printf 'caddy_security_module=%s\n' "${CADDY_SECURITY_MODULE}"
    printf 'filebrowser_version=%s\n' "${FILEBROWSER_VERSION}"
    printf 'runpodctl_version=%s\n' "${RUNPODCTL_VERSION}"
    printf 'huggingface_hub_version=%s\n' "${HUGGINGFACE_HUB_VERSION}"
    printf 'filebrowser_linux_amd64_sha256=%s\n' "${FILEBROWSER_LINUX_AMD64_SHA256}"
    printf 'runpodctl_linux_amd64_sha256=%s\n' "${RUNPODCTL_LINUX_AMD64_SHA256}"
    printf 'runtime_script_hash=%s\n' "${RUNTIME_SCRIPT_HASH}"
    printf 'rootfs_hash=%s\n' "${ROOTFS_HASH}"
    hash_files .dockerignore docker/Dockerfile.runtime-tools
  } | hash_payload
)"

BASIC_KEY="$(
  {
    printf 'stage=custom-basic\n'
    printf 'parent_key=%s\n' "${TOOLS_KEY}"
    printf 'comfyui_manager_ref=%s\n' "${COMFYUI_MANAGER_REF}"
    printf 'kjnodes_ref=%s\n' "${KJNODES_REF}"
    printf 'rgthree_ref=%s\n' "${RGTHREE_REF}"
    printf 'crystools_ref=%s\n' "${CRYSTOOLS_REF}"
    printf 'custom_install_script_hash=%s\n' "${CUSTOM_INSTALL_SCRIPT_HASH}"
    hash_files .dockerignore docker/Dockerfile.custom-basic
  } | hash_payload
)"

IMAGE_KEY="$(
  {
    printf 'stage=custom-image\n'
    printf 'parent_key=%s\n' "${BASIC_KEY}"
    printf 'controlnet_aux_ref=%s\n' "${CONTROLNET_AUX_REF}"
    printf 'impact_pack_ref=%s\n' "${IMPACT_PACK_REF}"
    printf 'sapiens2_easy_ref=%s\n' "${SAPIENS2_EASY_REF}"
    printf 'depth_anything_v3_ref=%s\n' "${DEPTH_ANYTHING_V3_REF}"
    printf 'custom_install_script_hash=%s\n' "${CUSTOM_INSTALL_SCRIPT_HASH}"
    hash_files .dockerignore docker/Dockerfile.custom-image
  } | hash_payload
)"

VIDEO_KEY="$(
  {
    printf 'stage=custom-video\n'
    printf 'parent_key=%s\n' "${BASIC_KEY}"
    printf 'video_helper_suite_ref=%s\n' "${VIDEO_HELPER_SUITE_REF}"
    printf 'seedvr2_video_upscaler_ref=%s\n' "${SEEDVR2_VIDEO_UPSCALER_REF}"
    printf 'wan_video_wrapper_ref=%s\n' "${WAN_VIDEO_WRAPPER_REF}"
    printf 'ltx_video_ref=%s\n' "${LTX_VIDEO_REF}"
    printf 'custom_install_script_hash=%s\n' "${CUSTOM_INSTALL_SCRIPT_HASH}"
    hash_files .dockerignore docker/Dockerfile.custom-video
  } | hash_payload
)"

{
  echo "image_name_lc=${IMAGE_NAME_LC}"
  echo "version_slug=${VERSION_SLUG}"
  echo "short_sha=${SHORT_SHA}"
  echo "comfyui_image=${IMAGE_NAME_LC}:sha-${SHORT_SHA}-comfyui"
  echo "comfyui_build_image=${IMAGE_NAME_LC}:buildkey-comfyui-${COMFYUI_KEY}"
  echo "optimized_image=${IMAGE_NAME_LC}:sha-${SHORT_SHA}-optimized"
  echo "optimized_build_image=${IMAGE_NAME_LC}:buildkey-optimized-${OPTIMIZED_KEY}"
  echo "tools_image=${IMAGE_NAME_LC}:sha-${SHORT_SHA}-runtime-tools"
  echo "tools_build_image=${IMAGE_NAME_LC}:buildkey-runtime-tools-${TOOLS_KEY}"
  echo "basic_image=${IMAGE_NAME_LC}:sha-${SHORT_SHA}-custom-basic"
  echo "basic_build_image=${IMAGE_NAME_LC}:buildkey-custom-basic-${BASIC_KEY}"
  echo "image_image=${IMAGE_NAME_LC}:sha-${SHORT_SHA}-custom-image"
  echo "image_build_image=${IMAGE_NAME_LC}:buildkey-custom-image-${IMAGE_KEY}"
  echo "video_image=${IMAGE_NAME_LC}:sha-${SHORT_SHA}-custom-video"
  echo "video_build_image=${IMAGE_NAME_LC}:buildkey-custom-video-${VIDEO_KEY}"
} >> "${GITHUB_OUTPUT}"
