#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: build-local.sh <basic|basic-unoptimized> [docker buildx options...]" >&2
  exit 1
fi

variant="$1"
shift

case "${variant}" in
  basic)
    optimization_stage=optimized
    ;;
  basic-unoptimized)
    optimization_stage=unoptimized
    ;;
  *)
    echo "Unsupported image variant: ${variant}" >&2
    exit 1
    ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck disable=SC1091
source "${repo_root}/docker.env"
set +a

docker buildx build \
  --file "${repo_root}/docker/Dockerfile.basic" \
  --target basic \
  --platform linux/amd64 \
  --build-arg "BASE_IMAGE=${PYTORCH_BASE_IMAGE}" \
  --build-arg "OPTIMIZATION_STAGE=${optimization_stage}" \
  --build-arg COMFYUI_REF \
  --build-arg TRANSFORMERS_VERSION \
  --build-arg XFORMERS_VERSION \
  --build-arg FLASH_ATTN_VERSION \
  --build-arg CADDY_VERSION \
  --build-arg CADDY_SECURITY_MODULE \
  --build-arg FILEBROWSER_VERSION \
  --build-arg RUNPODCTL_VERSION \
  --build-arg HUGGINGFACE_HUB_VERSION \
  --build-arg FILEBROWSER_LINUX_AMD64_SHA256 \
  --build-arg RUNPODCTL_LINUX_AMD64_SHA256 \
  --build-arg COMFYUI_MANAGER_REF \
  --build-arg KJNODES_REF \
  --build-arg RGTHREE_REF \
  --build-arg CRYSTOOLS_REF \
  --tag "runpod-comfyui:${variant}" \
  "$@" \
  "${repo_root}"
