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

link_model_alias() {
  local canonical="$1"
  local alias_name="$2"
  local canonical_path="${STORAGE_DIR}/models/${canonical}"
  local alias_path="${STORAGE_DIR}/models/${alias_name}"

  mkdir -p "${canonical_path}"

  if [[ -L "${alias_path}" ]]; then
    rm "${alias_path}"
  elif [[ -d "${alias_path}" ]]; then
    rsync -a "${alias_path}/" "${canonical_path}/"
    rm -rf "${alias_path}"
  elif [[ -e "${alias_path}" ]]; then
    rm -f "${alias_path}"
  fi

  ln -s "${canonical_path}" "${alias_path}"
}

if [[ -d /opt/bootstrap/baked-custom-nodes ]]; then
  rsync -a --ignore-existing /opt/bootstrap/baked-custom-nodes/ "${STORAGE_DIR}/custom_nodes/"
fi

# Normalize common model folder aliases so either naming convention works.
link_model_alias "checkpoints" "diffusion_models"
link_model_alias "checkpoints" "unet"
link_model_alias "clip" "text_encoders"
link_model_alias "controlnet" "t2i_adapter"

cat > "${COMFYUI_DIR}/extra_model_paths.yaml" <<EOF
runpod:
  base_path: ${STORAGE_DIR}/models
  checkpoints: checkpoints
  diffusion_models: diffusion_models
  unet: unet
  configs: configs
  vae: vae
  loras: loras
  upscale_models: upscale_models
  embeddings: embeddings
  hypernetworks: hypernetworks
  controlnet: controlnet
  t2i_adapter: t2i_adapter
  clip: clip
  text_encoders: text_encoders
  clip_vision: clip_vision
  style_models: style_models
  diffusers: diffusers
  gligen: gligen
EOF

link_path "${STORAGE_DIR}/custom_nodes" "${COMFYUI_DIR}/custom_nodes"
link_path "${STORAGE_DIR}/input" "${COMFYUI_DIR}/input"
link_path "${STORAGE_DIR}/models" "${COMFYUI_DIR}/models"
link_path "${STORAGE_DIR}/output" "${COMFYUI_DIR}/output"
link_path "${STORAGE_DIR}/temp" "${COMFYUI_DIR}/temp"
link_path "${STORAGE_DIR}/user" "${COMFYUI_DIR}/user"
