# Build Reference

## Image model

### Variant dimensions

- `stable`
  Includes the recovery-friendly wheel cache in `/opt/wheels`.
- `slim`
  Removes the wheel cache to reduce runtime image size.
- `default-pack`
  Includes the full baked custom node pack.
- `manager-only`
  Bakes only `ComfyUI-Manager`.
- `safe`
  Conservative runtime.
- `aggressive`
  Adds experimental optimization packages.

### Published workflow variants

The GitHub Actions workflow currently publishes these explicit `stable` variants:

- `stable-default-aggr`
- `stable-default-safe`
- `stable-manager-aggr`
- `stable-manager-safe`

`stable-default-aggr` is treated as the canonical build and also receives `latest` and bare release tags (e.g. `v1.0.2`).

### Image tags

Each variant receives the following tags on release:

| Tag pattern | Example | Scope |
|---|---|---|
| `<release-tag>` | `v1.0.2` | canonical only |
| `<release-tag>-<variant>` | `v1.0.2-stable-default-aggr` | all variants |
| `<version-slug>-<variant>` | `py311-pt210-cu128-cf019-stable-default-aggr` | all variants |
| `<variant>` | `stable-default-aggr` | all variants |
| `sha-<hash>-<variant>` | `sha-abc1234-stable-default-aggr` | all variants |
| `latest` | `latest` | canonical only |

The version slug encodes the runtime stack: Python, PyTorch, CUDA, and ComfyUI versions (3 digits each, dots stripped).

## Build arguments

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_REF` | `v0.19.0` | ComfyUI git ref |
| `COMFYUI_MANAGER_REF` | `main` | ComfyUI-Manager git ref |
| `IMPACT_PACK_REF` | `Main` | Impact Pack git ref |
| `WAN_VIDEO_WRAPPER_REF` | `main` | WanVideoWrapper git ref |
| `CODE_SERVER_VERSION` | `4.103.2` | code-server version |
| `PYTHON_VERSION` | `3.11.15` | Exact CPython version compiled into the image |
| `XFORMERS_INSTALL_MODE` | `wheel` | Default xformers install path |
| `INCLUDE_DEFAULT_CUSTOM_NODE_PACK` | `1` | Set to `0` to bake only `ComfyUI-Manager` |
| `INCLUDE_WAN_VIDEO_WRAPPER` | `0` | Set to `1` to bake in WanVideoWrapper |
| `ENABLE_AGGRESSIVE_OPTIMIZATIONS` | `0` | Set to `1` to install experimental optimization packages |
| `TRITON_VERSION` | `3.6.0` | Triton version for aggressive builds |
| `SAGEATTENTION_VERSION` | `0.1.0` | SageAttention version for aggressive builds |

## Runtime environment variables

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_PORT` | `8188` | ComfyUI port |
| `CODE_SERVER_PORT` | `8080` | code-server port |
| `COMFYUI_HOST` | `0.0.0.0` | ComfyUI bind address |
| `CODE_SERVER_HOST` | `0.0.0.0` | code-server bind address |
| `CODE_SERVER_AUTH` | `none` | code-server auth mode |
| `CLI_ARGS` | empty | Extra ComfyUI CLI flags |

## Dockerfile architecture

### Multi-stage build

The Dockerfile uses three stages to maximize build cache efficiency:

1. **`python-builder`** -- Compiles CPython from source in an isolated stage. Changes to ComfyUI refs, scripts, or pip dependencies never trigger a Python recompilation.
2. **`builder`** -- Installs code-server, PyTorch, xformers, ComfyUI, and custom nodes. Uses BuildKit cache mounts for pip and apt.
3. **`runtime-base`** -- Minimal runtime image based on `cuda:*-runtime` (not `-devel`). Copies only the artifacts needed from builder.

### BuildKit cache mounts

All `pip install` and `apt-get` commands use `--mount=type=cache` with per-stage IDs to avoid cross-contamination between devel and runtime base images:

- `apt-python-builder`, `apt-builder`, `apt-runtime` -- apt package caches
- `pip-builder` -- pip wheel download cache

### CI cache

The GitHub Actions workflow uses GHCR registry-based caching (`type=registry`) instead of the default GHA cache to avoid the 10 GB repository cache limit. Each matrix variant stores its cache independently:

```text
ghcr.io/bogyie/runpod-comfyui:cache-stable-default-aggr
ghcr.io/bogyie/runpod-comfyui:cache-stable-default-safe
...
```

Cache writes are skipped on PR builds to avoid permission errors from fork contexts.

## Build-time guardrails

- A protected package manifest is captured after the base `torch/torchvision/torchaudio/xformers` install.
- After each baked custom node install step, the build verifies that critical packages have not drifted.
- The guarded package set includes `torch`, `torchvision`, `torchaudio`, `xformers`, `triton`, and `sageattention`.
- If a baked custom node tries to replace those packages unexpectedly, the Docker build fails.
- `aggressive` variants intentionally install `triton` and `sageattention`, then refresh the protected manifest after that step.

Custom node refs are resolved defensively during the build:

- Remote branches are checked out from `origin/<ref>` when they exist.
- Tags and commit SHAs are checked out directly.
- The build fails fast if a requested ref does not exist.

All git clones use `--depth 1` to minimize image size and build time.

## GitHub Actions notes

- Builds are triggered on **GitHub Release** (published), **pull request**, and **manual dispatch** -- not on push to main.
- The workflow uses explicit matrix entries instead of a full cartesian matrix so additional variants can be added later without making tags noisy.
- `fail-fast: false` ensures all variants build independently.
- `timeout-minutes: 90` prevents hung builds from consuming runner hours.
- `concurrency` control cancels in-progress builds when a new one is triggered for the same ref and variant.
- PR smoke tests use a GPU-safe import check so builds can still validate on GitHub-hosted runners without NVIDIA drivers.
- code-server is installed from the GitHub Releases `.deb` package directly, avoiding the rate-limited `code-server.dev` install script.

## Suggested next improvements

- Pin known-good git commits for ComfyUI and baked custom nodes.
- Add a healthcheck script for ports `8188` and `8080`.
- Add helper scripts for downloading models into the persistent volume.
- Add alternate compatibility or optimization image flavors after validation.
