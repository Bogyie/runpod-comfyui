#!/usr/bin/env bash
set -euo pipefail

echo "Disk usage before cleanup:"
df -h /

paths=(
  /usr/share/dotnet
  /usr/local/lib/android
  /opt/ghc
  /usr/local/.ghcup
  /usr/local/share/boost
  /usr/local/share/powershell
  /usr/share/swift
  /opt/az
)

if [[ -n "${AGENT_TOOLSDIRECTORY:-}" ]]; then
  paths+=("${AGENT_TOOLSDIRECTORY}")
fi

sudo rm -rf "${paths[@]}"
sudo apt-get clean
sudo docker system prune --all --force --volumes
sudo docker builder prune --all --force

echo "Disk usage after cleanup:"
df -h /
