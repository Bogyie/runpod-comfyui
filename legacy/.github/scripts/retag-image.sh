#!/usr/bin/env bash
set -euo pipefail

source_image="$1"
shift

args=()
for tag in "$@"; do
  if [[ -n "${tag}" ]]; then
    args+=("-t" "${tag}")
  fi
done

if (( ${#args[@]} == 0 )); then
  echo "No target tags supplied for ${source_image}" >&2
  exit 1
fi

docker buildx imagetools create "${args[@]}" "${source_image}"
