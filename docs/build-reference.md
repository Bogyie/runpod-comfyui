# Build Reference

## Image model

### Linear stage chain

The build is intentionally linear. Each Dockerfile produces a published stage image, and the next Dockerfile consumes that image through `BASE_IMAGE`.

| Stage | Dockerfile | Adds |
|---|---|---|
| `core` | `docker/Dockerfile.core` | CUDA runtime, CPython, ComfyUI, PyTorch, Transformers, `ComfyUI-Manager` |
| `runtime-tools` | `docker/Dockerfile.runtime-tools` | `huggingface_hub[cli]`, `runpodctl`, `wget`, `jq`, SSH client, `code-server` |
| `optimized` | `docker/Dockerfile.optimized` | xformers and FlashAttention |
| `custom-basic` | `docker/Dockerfile.custom-basic` | `kijai/ComfyUI-KJNodes` |
| `custom-advanced` | `docker/Dockerfile.custom-advanced` | `Bogyie/ComfyUI-Sapiens2-Easy` |

The purpose is to keep expensive base layers reusable. A custom-node-only change should rebuild only the custom-node stage and its downstream stages, not Python, PyTorch, ComfyUI, or runtime tools.

Within a workflow run, `BASE_IMAGE` points at the SHA-scoped stage tag such as `sha-abc1234-core` instead of the mutable `core` tag. This avoids cross-branch or concurrent-run collisions while still publishing readable stage tags.

### Published stage tags

The GitHub Actions workflow publishes these stage tags:

- `core`
- `runtime-tools`
- `optimized`
- `custom-basic`
- `custom-advanced`

`custom-advanced` is treated as the canonical final image and receives `latest` and bare release tags.

### Image tags

Each stage receives the following tags on release:

| Tag pattern | Example | Scope |
|---|---|---|
| `<stage>` | `custom-advanced` | all stages |
| `<release-tag>-<stage>` | `v1.0.2-custom-advanced` | all stages |
| `<version-slug>-<stage>` | `py311-pt210-cu128-cf024-custom-advanced` | all stages |
| `sha-<hash>-<stage>` | `sha-abc1234-custom-advanced` | all stages |
| `<release-tag>` | `v1.0.2` | canonical final only |
| `latest` | `latest` | canonical final only |

The version slug encodes Python, PyTorch, CUDA, and ComfyUI versions.

The canonical final image is also pushed to Docker Hub as `docker.io/bogyie/runpod-comfyui` on release.

## Build arguments

### Core

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_REF` | `v0.24.0` | ComfyUI git ref |
| `COMFYUI_MANAGER_REF` | `main` | ComfyUI-Manager git ref |
| `TRANSFORMERS_VERSION` | `5.12.0` | Transformers version |
| `PYTHON_VERSION` | `3.11.15` | Exact CPython version compiled into the image |

### Runtime tools

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | required | Previous stage image |
| `CODE_SERVER_VERSION` | `4.103.2` | code-server version |

### Optimized

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | required | Previous stage image |
| `XFORMERS_VERSION` | `0.0.35` | xformers version |
| `FLASH_ATTN_VERSION` | `2.8.3` | FlashAttention version |
| `MAX_JOBS` | `4` | FlashAttention build parallelism cap |

### Custom nodes

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | required | Previous stage image |
| `BASIC_NODE_REF` | `main` | `ComfyUI-KJNodes` git ref |
| `ADVANCED_NODE_REF` | `main` | `ComfyUI-Sapiens2-Easy` git ref |

## Runtime environment variables

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_PORT` | `8188` | ComfyUI port |
| `CODE_SERVER_PORT` | `8080` | code-server port |
| `COMFYUI_HOST` | `0.0.0.0` | ComfyUI bind address |
| `CODE_SERVER_HOST` | `0.0.0.0` | code-server bind address |
| `CODE_SERVER_AUTH` | `none` | code-server auth mode |
| `CLI_ARGS` | empty | Extra ComfyUI CLI flags |

## Cache strategy

Each stage has two cache layers:

- Dockerfile-level BuildKit cache mounts for apt and pip work inside the stage.
- Registry cache per stage, for example `cache-core`, `cache-optimized`, and `cache-custom-advanced`.

The workflow builds stages in order:

```text
core -> runtime-tools -> optimized -> custom-basic -> custom-advanced
```

On release and manual dispatch, each stage runs in its own GitHub Actions job. A stage job pushes its SHA-scoped image and registry cache to GHCR before the next job consumes that image through `BASE_IMAGE`.

## Build-time guardrails

- A protected package manifest is captured after the core dependency install.
- The manifest tracks `torch`, `torchvision`, `torchaudio`, `transformers`, `xformers`, `flash-attn`, `triton`, and `sageattention`.
- The optimized stage refreshes the manifest after installing xformers and FlashAttention.
- Custom-node stages verify the manifest after installing node requirements.
- If a custom node replaces protected packages unexpectedly, the Docker build fails.

## GitHub Actions notes

- Builds are triggered on **GitHub Release** (published) and **manual dispatch**.
- The workflow uses dependent jobs instead of a matrix so each stage can reuse the previous stage image while remaining separately visible and retryable in GitHub Actions.
- Each stage has its own timeout so a later-stage failure does not consume the same budget as the full chain.
- `concurrency` cancels in-progress builds for the same ref.
- The final `custom-advanced` job runs a GPU-safe smoke test without requiring an NVIDIA driver.

## Suggested next improvements

- Pin known-good git commits for ComfyUI-Manager and both baked custom nodes.
- Add a healthcheck script for ports `8188` and `8080`.
- Add helper scripts for downloading models into the persistent volume.
