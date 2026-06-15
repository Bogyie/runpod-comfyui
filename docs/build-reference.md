# Build Reference

## Image model

### Build dimensions

- `stable` (single runtime target)
  Includes `code-server`, `runpodctl`, and the recovery-friendly wheel cache in `/opt/wheels`.
- `CUSTOM_NODE_PROFILE`
  Selects which custom node pack is baked: `default`, `image`, `3d`, or `video`.
  Every profile bakes `ComfyUI-Manager` plus the default pack; non-default
  profiles add their own pack on top.
- `safe`
  Conservative runtime (no aggressive optimization extras).
- `aggressive`
  Adds experimental optimization packages (`triton`, `sageattention`).

### Custom node packs

The repos cloned for each profile live in `custom-nodes/*.txt`, one git URL per
line. Editing these files is the only change needed to add or remove a baked
node -- the `Dockerfile` never lists individual repos.

- `custom-nodes/default.txt` -- baked into **every** profile:
  - `rgthree-comfy`
  - `ComfyUI-KJNodes`
  - `ComfyUI-Impact-Pack`
  - `ComfyUI-Easy-Use`
- `custom-nodes/image.txt` -- added for the `image` profile:
  - `comfyui-portrait-master`
  - `ComfyUI-Sapiens2-Easy`
  - `comfyui_controlnet_aux`
- `custom-nodes/3d.txt` -- added for the `3d` profile:
  - `ComfyUI-Sapiens2-Easy`
  - `ComfyUI-3D-Pack`
- `custom-nodes/video.txt` -- added for the `video` profile:
  - `ComfyUI-VideoHelperSuite`
  - `ComfyUI-WanVideoWrapper`
  - `ComfyUI-SeedVR2_VideoUpscaler`
  - `ComfyUI-FFmpeg`

### Published workflow variants

The GitHub Actions workflow publishes these explicit variants:

- `default-opt-enabled` (default profile + aggressive optimizations)
- `default-opt-disabled` (default profile, no aggressive optimizations)
- `image` (image profile + aggressive optimizations)
- `3d` (3d profile + aggressive optimizations)
- `video` (video profile + aggressive optimizations)

`default-opt-enabled` is treated as the canonical build and also receives `latest` and bare release tags (e.g. `v1.0.2`).

### Image tags

Each variant receives the following tags on release:

| Tag pattern | Example | Scope |
|---|---|---|
| `<release-tag>` | `v1.0.2` | canonical only |
| `<release-tag>-<variant>` | `v1.0.2-default-opt-enabled` | all variants |
| `<version-slug>-<variant>` | `py311-pt210-cu128-cf024-default-opt-enabled` | all variants |
| `<variant>` | `default-opt-enabled` | all variants |
| `sha-<hash>-<variant>` | `sha-abc1234-default-opt-enabled` | all variants |
| `latest` | `latest` | canonical only |

The version slug encodes the runtime stack: Python, PyTorch, CUDA, and ComfyUI versions (3 digits each, dots stripped).

All variants are published to GHCR (`ghcr.io/bogyie/runpod-comfyui`).

## Build arguments

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_REF` | `v0.24.0` | ComfyUI git ref |
| `COMFYUI_MANAGER_REF` | `main` | ComfyUI-Manager git ref |
| `CODE_SERVER_VERSION` | `4.103.2` | code-server version |
| `PYTHON_VERSION` | `3.11.15` | Exact CPython version compiled into the image |
| `XFORMERS_INSTALL_MODE` | `wheel` | Default xformers install path |
| `CUSTOM_NODE_PROFILE` | `default` | Baked custom node profile: `default`, `image`, `3d`, or `video` |
| `BUILD_WHEEL_CACHE` | `1` | Set to `0` to skip downloading the recovery wheel cache |
| `ENABLE_AGGRESSIVE_OPTIMIZATIONS` | `0` | Set to `1` to install experimental optimization packages |
| `TRITON_VERSION` | `3.6.0` | Triton version for aggressive builds |
| `SAGEATTENTION_VERSION` | `0.1.0` | SageAttention version for aggressive builds |
| `TRANSFORMERS_VERSION` | `5.12.0` | Pinned `transformers` version (ENV; protected from node drift) |

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
2. **`builder`** -- Installs code-server, PyTorch, xformers, `transformers`, ComfyUI, and custom nodes. Uses BuildKit cache mounts for pip and apt.
3. **`runtime-core`** -- Minimal runtime image based on `cuda:*-runtime` (not `-devel`). Copies only the artifacts needed to run ComfyUI.
4. **`stable`** -- Adds `code-server`, `runpodctl`, and `/opt/wheels` on top of the core runtime.

### BuildKit cache mounts

All `pip install` and `apt-get` commands use `--mount=type=cache` with per-stage IDs to avoid cross-contamination between devel and runtime base images:

- `apt-python-builder`, `apt-builder`, `apt-runtime` -- apt package caches
- `pip-builder` -- pip wheel download cache

### CI cache

The GitHub Actions workflow uses GHCR registry-based caching (`type=registry`) instead of the default GHA cache to avoid the 10 GB repository cache limit. Each matrix variant stores its cache independently:

```text
ghcr.io/bogyie/runpod-comfyui:cache-default-opt-enabled
ghcr.io/bogyie/runpod-comfyui:cache-default-opt-disabled
ghcr.io/bogyie/runpod-comfyui:cache-image
ghcr.io/bogyie/runpod-comfyui:cache-3d
ghcr.io/bogyie/runpod-comfyui:cache-video
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
- All variants publish to GHCR; there is no Docker Hub mirror.
- The "Free disk space" step prunes preinstalled toolchains and BuildKit GC keeps the cache bounded, since the full node packs plus wheel cache can otherwise exhaust the runner's disk (`No space left on device`).

## Suggested next improvements

- Pin known-good git commits for ComfyUI and baked custom nodes.
- Add a healthcheck script for ports `8188` and `8080`.
- Add helper scripts for downloading models into the persistent volume.
- Add alternate compatibility or optimization image flavors after validation.
