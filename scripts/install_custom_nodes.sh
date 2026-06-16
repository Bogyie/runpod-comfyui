#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
PROTECTED_MANIFEST="${PROTECTED_MANIFEST:-/opt/bootstrap/protected-package-manifest.json}"

if (( $# % 3 != 0 )); then
  echo "Usage: install_custom_nodes.sh <name> <repo-url> <ref> [<name> <repo-url> <ref> ...]" >&2
  exit 1
fi

checkout_repo_ref() {
  local repo_dir="$1"
  local ref="$2"

  [[ -n "${ref}" ]] || return 0
  if git -C "${repo_dir}" ls-remote --exit-code --heads origin "${ref}" >/dev/null 2>&1; then
    git -C "${repo_dir}" fetch --depth 1 origin "refs/heads/${ref}:refs/remotes/origin/${ref}"
    git -C "${repo_dir}" checkout -B "${ref}" "origin/${ref}"
  elif git -C "${repo_dir}" ls-remote --exit-code --tags origin "${ref}" >/dev/null 2>&1; then
    git -C "${repo_dir}" fetch --depth 1 origin "refs/tags/${ref}:refs/tags/${ref}"
    git -C "${repo_dir}" checkout "${ref}"
  else
    git -C "${repo_dir}" fetch --depth 1 origin "${ref}" || {
      echo "Requested ref '${ref}' was not found for ${repo_dir}" >&2
      exit 1
    }
    git -C "${repo_dir}" checkout FETCH_HEAD
  fi
}

mkdir -p "${COMFYUI_DIR}/custom_nodes"

while (( $# > 0 )); do
  name="$1"
  repo_url="$2"
  ref="$3"
  shift 3

  node_dir="${COMFYUI_DIR}/custom_nodes/${name}"
  rm -rf "${node_dir}"
  git clone --depth 1 --filter=blob:none "${repo_url}" "${node_dir}"
  checkout_repo_ref "${node_dir}" "${ref}"

  if [[ -f "${node_dir}/requirements.txt" ]]; then
    "${COMFY_VENV}/bin/python" -m pip install -r "${node_dir}/requirements.txt"
  fi
  if [[ -f "${node_dir}/install.py" ]]; then
    (cd "${node_dir}" && COMFYUI_FOLDERS_BASE_PATH="${COMFYUI_DIR}" "${COMFY_VENV}/bin/python" install.py)
  fi

  if [[ -f "${PROTECTED_MANIFEST}" ]]; then
    "${COMFY_VENV}/bin/python" /opt/bootstrap/scripts/verify_protected_packages.py \
      verify \
      "${PROTECTED_MANIFEST}"
  fi
done

rm -rf /opt/bootstrap/baked-custom-nodes
mkdir -p /opt/bootstrap/baked-custom-nodes
cp -a "${COMFYUI_DIR}/custom_nodes/." /opt/bootstrap/baked-custom-nodes/
"${COMFY_VENV}/bin/python" -m pip freeze > /opt/bootstrap/base-requirements.lock
