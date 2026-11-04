#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" || "${RUNNER_ENVIRONMENT:-}" != "github-hosted" ]]; then
  echo "Cleanup is restricted to disposable GitHub-hosted runners" >&2
  exit 1
fi

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
