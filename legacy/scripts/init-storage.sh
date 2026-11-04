#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
STORAGE_DIR="${STORAGE_DIR:-/workspace/storage}"

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

ensure_model_dir() {
  local path="$1"
  local migration_dir

  mkdir -p "$(dirname "${path}")"
  if [[ -L "${path}" ]]; then
    migration_dir="$(mktemp -d "${path}.migration.XXXXXX")"
    if [[ -d "${path}" ]]; then
      rsync -a --ignore-existing "${path}/" "${migration_dir}/"
    fi
    rm "${path}"
    mkdir -p "${path}"
    rsync -a --ignore-existing "${migration_dir}/" "${path}/"
    rm -rf "${migration_dir}"
  else
    mkdir -p "${path}"
  fi
}

link_model_alias() {
  local canonical="$1"
  local alias_name="$2"
  local canonical_path="${STORAGE_DIR}/models/${canonical}"
  local alias_path="${STORAGE_DIR}/models/${alias_name}"
  local alias_real
  local canonical_real

  ensure_model_dir "${canonical_path}"

  if [[ -L "${alias_path}" ]]; then
    if [[ -d "${alias_path}" ]]; then
      alias_real="$(cd "${alias_path}" && pwd -P)"
      canonical_real="$(cd "${canonical_path}" && pwd -P)"
      if [[ "${alias_real}" != "${canonical_real}" ]]; then
        rsync -a --ignore-existing "${alias_path}/" "${canonical_path}/"
      fi
    fi
    rm "${alias_path}"
  elif [[ -d "${alias_path}" ]]; then
    rsync -a "${alias_path}/" "${canonical_path}/"
    rm -rf "${alias_path}"
  elif [[ -e "${alias_path}" ]]; then
    rm -f "${alias_path}"
  fi

  ln -s "${canonical_path}" "${alias_path}"
}

mkdir -p \
  "${STORAGE_DIR}/custom_nodes" \
  "${STORAGE_DIR}/custom_nodes.disabled" \
  "${STORAGE_DIR}/input" \
  "${STORAGE_DIR}/output" \
  "${STORAGE_DIR}/temp" \
  "${STORAGE_DIR}/user/default/workflows" \
  "${WORKSPACE_DIR}/logs"

for model_dir in \
  checkpoints \
  clip \
  clip_vision \
  configs \
  controlnet \
  diffusion_models \
  diffusers \
  embeddings \
  gligen \
  hypernetworks \
  loras \
  style_models \
  upscale_models \
  vae; do
  ensure_model_dir "${STORAGE_DIR}/models/${model_dir}"
done

if [[ -d /opt/bootstrap/baked-custom-nodes ]]; then
  rsync -a --ignore-existing /opt/bootstrap/baked-custom-nodes/ "${STORAGE_DIR}/custom_nodes/"
fi

# Normalize common model folder aliases so either naming convention works.
link_model_alias "diffusion_models" "unet"
link_model_alias "clip" "text_encoders"
link_model_alias "controlnet" "t2i_adapter"

cat > "${COMFYUI_DIR}/extra_model_paths.yaml" <<EOF
runpod:
  base_path: ${STORAGE_DIR}/models
  checkpoints: checkpoints
  diffusion_models: |
    diffusion_models
    unet
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
