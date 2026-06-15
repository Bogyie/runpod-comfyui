#!/usr/bin/env bash
# Clone the baked custom nodes for a given build profile.
#
# Every profile includes ComfyUI-Manager and the default pack
# (custom-nodes/default.txt). Non-default profiles additionally clone the
# repos listed in custom-nodes/<profile>.txt.
#
# The repo lists live OUTSIDE this script (custom-nodes/*.txt) so that adding
# or removing a node never requires touching the Dockerfile.
#
# Usage:
#   install-custom-nodes.sh <profile> <comfyui_dir> <pack_dir>
#
#   profile      one of: default image 3d video
#   comfyui_dir  ComfyUI checkout (custom_nodes lives under here)
#   pack_dir     directory holding default.txt, image.txt, 3d.txt, video.txt
set -euo pipefail

PROFILE="${1:?profile required (default|image|3d|video)}"
COMFYUI_DIR="${2:?comfyui dir required}"
PACK_DIR="${3:?pack dir required}"

CUSTOM_NODES_DIR="${COMFYUI_DIR}/custom_nodes"
COMFYUI_MANAGER_REF="${COMFYUI_MANAGER_REF:-main}"

case "${PROFILE}" in
  default | image | 3d | video) ;;
  *)
    echo "Unsupported custom node profile: ${PROFILE}" >&2
    echo "Expected one of: default image 3d video" >&2
    exit 1
    ;;
esac

mkdir -p "${CUSTOM_NODES_DIR}"

# Resolve a git ref defensively: prefer remote branches, fall back to tags/SHAs.
checkout_repo_ref() {
  local repo_dir="$1"
  local ref="$2"
  [[ -n "${ref}" ]] || return 0
  if git -C "${repo_dir}" show-ref --verify --quiet "refs/remotes/origin/${ref}"; then
    git -C "${repo_dir}" checkout -B "${ref}" "origin/${ref}"
  elif git -C "${repo_dir}" rev-parse --verify --quiet "${ref}^{commit}" >/dev/null; then
    git -C "${repo_dir}" checkout "${ref}"
  else
    echo "Requested ref '${ref}' was not found for ${repo_dir}" >&2
    exit 1
  fi
}

# Derive the custom_nodes subdir name from a git URL (strip trailing .git).
repo_dir_name() {
  local url="$1"
  local base
  base="$(basename "${url}")"
  printf '%s' "${base%.git}"
}

clone_pack() {
  local pack_file="$1"
  [[ -f "${pack_file}" ]] || {
    echo "Pack file not found: ${pack_file}" >&2
    exit 1
  }
  local url name target
  while IFS= read -r url || [[ -n "${url}" ]]; do
    # Strip comments and surrounding whitespace.
    url="${url%%#*}"
    url="${url#"${url%%[![:space:]]*}"}"
    url="${url%"${url##*[![:space:]]}"}"
    [[ -n "${url}" ]] || continue

    name="$(repo_dir_name "${url}")"
    target="${CUSTOM_NODES_DIR}/${name}"
    if [[ -d "${target}" ]]; then
      echo "Skipping ${name} (already present)"
      continue
    fi
    echo "Cloning ${name} from ${url}"
    git clone --depth 1 "${url}" "${target}"
  done <"${pack_file}"
}

# ComfyUI-Manager is always baked, independent of profile/pack files.
if [[ ! -d "${CUSTOM_NODES_DIR}/ComfyUI-Manager" ]]; then
  echo "Cloning ComfyUI-Manager"
  git clone --depth 1 "https://github.com/Comfy-Org/ComfyUI-Manager.git" \
    "${CUSTOM_NODES_DIR}/ComfyUI-Manager"
fi
checkout_repo_ref "${CUSTOM_NODES_DIR}/ComfyUI-Manager" "${COMFYUI_MANAGER_REF}"

# Default pack goes into every profile.
clone_pack "${PACK_DIR}/default.txt"

# Profile-specific pack stacks on top of the default pack.
if [[ "${PROFILE}" != "default" ]]; then
  clone_pack "${PACK_DIR}/${PROFILE}.txt"
fi

echo "Custom node install complete for profile '${PROFILE}'."
