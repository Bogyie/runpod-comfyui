#!/usr/bin/env bash
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-/opt/comfy/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-/opt/comfy/venv}"
PROTECTED_MANIFEST="${PROTECTED_MANIFEST:-/opt/bootstrap/protected-package-manifest.json}"
BAKED_CUSTOM_NODES_DIR="${BAKED_CUSTOM_NODES_DIR:-/opt/bootstrap/baked-custom-nodes}"
BASE_REQUIREMENTS_LOCK="${BASE_REQUIREMENTS_LOCK:-/opt/bootstrap/base-requirements.lock}"

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
if [[ -d "${BAKED_CUSTOM_NODES_DIR}" ]]; then
  rsync -a --delete "${BAKED_CUSTOM_NODES_DIR}/" "${COMFYUI_DIR}/custom_nodes/"
fi

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
    "${COMFY_VENV}/bin/python" -m pip install --no-compile -r "${node_dir}/requirements.txt"
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

rm -rf "${BAKED_CUSTOM_NODES_DIR}"
mkdir -p "${BAKED_CUSTOM_NODES_DIR}"
cp -a "${COMFYUI_DIR}/custom_nodes/." "${BAKED_CUSTOM_NODES_DIR}/"
find "${BAKED_CUSTOM_NODES_DIR}" -type d -name ".git" -prune -exec rm -rf {} +
find "${BAKED_CUSTOM_NODES_DIR}" -type d \
  \( -name ".github" -o -name "docs" -o -name "tests" -o -name "test" -o -name "__pycache__" \) \
  -prune -exec rm -rf {} +
find "${BAKED_CUSTOM_NODES_DIR}" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
rm -rf "${COMFYUI_DIR}/custom_nodes"
mkdir -p "$(dirname "${BASE_REQUIREMENTS_LOCK}")"
"${COMFY_VENV}/bin/python" -m pip freeze > "${BASE_REQUIREMENTS_LOCK}"
