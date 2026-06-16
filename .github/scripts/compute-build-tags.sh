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
    printf 'file:%s\n' "${path}"
    sha256sum "${path}"
  done
}

SCRIPT_HASH="$(
  find scripts -maxdepth 1 -type f -print \
    | sort \
    | while read -r path; do
        printf 'file:%s\n' "${path}"
        sha256sum "${path}"
      done \
    | sha256sum \
    | cut -d' ' -f1
)"

COMFYUI_KEY="$(
  {
    printf 'stage=comfyui\n'
    printf 'base_image=%s\n' "${PYTORCH_BASE_IMAGE}"
    printf 'comfyui_ref=v%s\n' "${COMFYUI_VERSION}"
    printf 'transformers_version=%s\n' "${TRANSFORMERS_VERSION}"
    printf 'scripts_hash=%s\n' "${SCRIPT_HASH}"
    hash_files .dockerignore docker/Dockerfile.comfyui start.sh
  } | hash_payload
)"

OPTIMIZED_KEY="$(
  {
    printf 'stage=optimized\n'
    printf 'parent_key=%s\n' "${COMFYUI_KEY}"
    printf 'xformers_version=%s\n' "${XFORMERS_VERSION}"
    printf 'flash_attn_version=%s\n' "${FLASH_ATTN_VERSION}"
    printf 'scripts_hash=%s\n' "${SCRIPT_HASH}"
    hash_files .dockerignore docker/Dockerfile.optimized
  } | hash_payload
)"

TOOLS_KEY="$(
  {
    printf 'stage=runtime-tools\n'
    printf 'parent_key=%s\n' "${OPTIMIZED_KEY}"
    printf 'code_server_version=%s\n' "${CODE_SERVER_VERSION}"
    printf 'scripts_hash=%s\n' "${SCRIPT_HASH}"
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
    printf 'scripts_hash=%s\n' "${SCRIPT_HASH}"
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
    printf 'scripts_hash=%s\n' "${SCRIPT_HASH}"
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
    printf 'scripts_hash=%s\n' "${SCRIPT_HASH}"
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
