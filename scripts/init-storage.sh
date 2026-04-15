#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
STORAGE_DIR="${STORAGE_DIR:-/workspace/storage}"

mkdir -p \
  "${STORAGE_DIR}/custom_nodes" \
  "${STORAGE_DIR}/custom_nodes.disabled" \
  "${STORAGE_DIR}/input" \
  "${STORAGE_DIR}/output" \
  "${STORAGE_DIR}/temp" \
  "${STORAGE_DIR}/user/default/workflows" \
  "${STORAGE_DIR}/models/checkpoints" \
  "${STORAGE_DIR}/models/clip" \
  "${STORAGE_DIR}/models/clip_vision" \
  "${STORAGE_DIR}/models/configs" \
  "${STORAGE_DIR}/models/controlnet" \
  "${STORAGE_DIR}/models/diffusers" \
  "${STORAGE_DIR}/models/embeddings" \
  "${STORAGE_DIR}/models/gligen" \
  "${STORAGE_DIR}/models/hypernetworks" \
  "${STORAGE_DIR}/models/loras" \
  "${STORAGE_DIR}/models/style_models" \
  "${STORAGE_DIR}/models/unet" \
  "${STORAGE_DIR}/models/upscale_models" \
  "${STORAGE_DIR}/models/vae" \
  "${WORKSPACE_DIR}/logs"

if [[ -d /opt/bootstrap/baked-custom-nodes ]]; then
  rsync -a --ignore-existing /opt/bootstrap/baked-custom-nodes/ "${STORAGE_DIR}/custom_nodes/"
fi

if [[ ! -f "${COMFYUI_DIR}/extra_model_paths.yaml" ]]; then
  cat > "${COMFYUI_DIR}/extra_model_paths.yaml" <<EOF
runpod:
  base_path: ${STORAGE_DIR}/models
  checkpoints: checkpoints
  configs: configs
  vae: vae
  loras: loras
  upscale_models: upscale_models
  embeddings: embeddings
  hypernetworks: hypernetworks
  controlnet: controlnet
  clip: clip
  clip_vision: clip_vision
  style_models: style_models
  diffusers: diffusers
  unet: unet
  gligen: gligen
EOF
fi

link_path() {
  local source="$1"
  local target="$2"

  if [[ -L "${target}" ]]; then
    rm "${target}"
  elif [[ -d "${target}" ]]; then
    rsync -a "${target}/" "${source}/"
    rm -rf "${target}"
  elif [[ -e "${target}" ]]; then
    rm -f "${target}"
  fi
  ln -s "${source}" "${target}"
}

link_path "${STORAGE_DIR}/custom_nodes" "${COMFYUI_DIR}/custom_nodes"
link_path "${STORAGE_DIR}/input" "${COMFYUI_DIR}/input"
link_path "${STORAGE_DIR}/output" "${COMFYUI_DIR}/output"
link_path "${STORAGE_DIR}/temp" "${COMFYUI_DIR}/temp"
link_path "${STORAGE_DIR}/user" "${COMFYUI_DIR}/user"
