#!/usr/bin/env bash
set -euo pipefail

image="$1"

echo "image_ref=${image}" >> "${GITHUB_OUTPUT}"
if docker buildx imagetools inspect "${image}" >/dev/null 2>&1; then
  echo "exists=true" >> "${GITHUB_OUTPUT}"
  echo "Reusing ${image}"
else
  echo "exists=false" >> "${GITHUB_OUTPUT}"
  echo "Building ${image}"
fi
