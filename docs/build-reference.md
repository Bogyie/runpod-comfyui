# Build Reference

## Image model

### Stage chain

The build uses the PyTorch Docker Hub image directly as its external base:

```text
pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel
```

Python, CUDA, PyTorch, torchvision, and torchaudio are intentionally inherited from that tag. The workflow does not carry separate Python/CUDA/PyTorch build arguments.

Each stage produces a pushed image. The next dependent job consumes the previous stage through a content-addressed `buildkey-<stage>-<hash>` image tag. If that buildkey image already exists, the job reuses it and only refreshes the run-specific tags.

| Stage | Dockerfile | Adds |
|---|---|---|
| `comfyui` | `docker/Dockerfile.comfyui` | ComfyUI, Transformers, startup scripts, storage helpers |
| `optimized` | `docker/Dockerfile.optimized` | xformers and FlashAttention wheels |
| `runtime-tools` | `docker/Dockerfile.runtime-tools` | Hugging Face CLI, git, curl, wget, runpodctl, GitHub CLI, code-server |
| `custom-basic` | `docker/Dockerfile.custom-basic` | ComfyUI-Manager, KJNodes, rgthree-comfy, Crystools |
| `custom-image` | `docker/Dockerfile.custom-image` | controlnet aux, Impact Pack, Sapiens2 Easy |
| `custom-video` | `docker/Dockerfile.custom-video` | VideoHelperSuite |

The dependency graph is:

```text
pytorch/pytorch
  -> comfyui
  -> optimized
  -> runtime-tools
  -> custom-basic
      -> custom-image
      -> custom-video
```

The final purpose stages run as separate parallel jobs after `custom-basic`.

### Published stage tags

The GitHub Actions workflow publishes these GHCR stage tags:

- `comfyui`
- `optimized`
- `runtime-tools`
- `custom-basic`
- `custom-image`
- `custom-video`

On release, the purpose images are also pushed to Docker Hub. `custom-image` additionally receives the bare release tag and `latest`.

### Image tags

Each stage receives these tags:

| Tag pattern | Example | Scope |
|---|---|---|
| `<stage>` | `custom-image` | all stages |
| `<release-tag>-<stage>` | `v1.0.2-custom-image` | release builds |
| `<base-slug>-cf<comfy>-<stage>` | `2-10-0-cuda12-8-cudnn9-devel-cf0240-custom-image` | all stages |
| `sha-<hash>-<stage>` | `sha-abc1234-custom-image` | all stages |
| `buildkey-<stage>-<hash>` | `buildkey-custom-image-abc123...` | all stages |
| `<release-tag>` | `v1.0.2` | `custom-image` only |
| `latest` | `latest` | `custom-image` only |

The base slug is derived from `PYTORCH_BASE_IMAGE`; it is not reconstructed from separate Python/CUDA/PyTorch variables.

## Build arguments

### ComfyUI

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel` | Upstream PyTorch image tag |
| `COMFYUI_REF` | `v0.24.0` | ComfyUI git ref |
| `TRANSFORMERS_VERSION` | `5.12.0` | Transformers version |

### Optimized

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | required | Previous stage image |
| `XFORMERS_VERSION` | `0.0.35` | xformers version |
| `FLASH_ATTN_VERSION` | `2.8.3` | FlashAttention version |

xformers is installed from the PyTorch CUDA wheel index with `--index-url` and `--only-binary`. The CUDA index suffix, such as `cu128`, is derived from the `torch.version.cuda` value inside the selected PyTorch base image. FlashAttention is resolved from the mjunya prebuilt wheel releases by detecting the Python ABI, torch version, CUDA version, and CPU architecture inside the current image.

### Runtime tools

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | required | Previous stage image |
| `CODE_SERVER_VERSION` | `4.103.2` | code-server version |

### Basic custom nodes

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | required | Previous stage image |
| `COMFYUI_MANAGER_REF` | `main` | ComfyUI-Manager git ref |
| `KJNODES_REF` | `main` | ComfyUI-KJNodes git ref |
| `RGTHREE_REF` | `main` | rgthree-comfy git ref |
| `CRYSTOOLS_REF` | `main` | ComfyUI-Crystools git ref |

### Purpose custom nodes

| Name | Default | Purpose |
|---|---|---|
| `CONTROLNET_AUX_REF` | `main` | comfyui_controlnet_aux git ref |
| `IMPACT_PACK_REF` | `Main` | ComfyUI-Impact-Pack git ref |
| `SAPIENS2_EASY_REF` | `main` | ComfyUI-Sapiens2-Easy git ref |
| `VIDEO_HELPER_SUITE_REF` | `main` | ComfyUI-VideoHelperSuite git ref |

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
- Registry cache per stage, for example `cache-comfyui`, `cache-optimized`, and `cache-custom-image`.
- Inline cache metadata in each pushed stage image, so stable tags can act as fallback cache sources.

Every stage job imports cache from the dedicated registry cache, the versioned stage tag, and the stable stage tag. It then pushes its SHA-scoped image, inline cache metadata, and registry cache before downstream jobs start.

Dockerfiles keep expensive install layers before volatile verification and cleanup scripts where possible, so script-only changes avoid reinstalling apt, pip, or custom-node dependencies.

Before building, each job checks whether its `buildkey-<stage>-<hash>` image already exists in GHCR. The hash includes that stage's Dockerfile, relevant build arguments, scripts copied into the image, and the parent stage build key. On a hit, the job skips Docker build and retags the existing image for the current SHA, stable stage tag, version tag, and release tags.

Refs such as `main` are hashed as configured ref strings. Pin a ref to a commit SHA, or resolve remote refs before hashing, when the build must detect upstream branch movement without changing workflow parameters.

## Build-time guardrails

- Each Dockerfile ends with `/opt/bootstrap/scripts/cleanup-image.sh`.
- Each Dockerfile then runs `/opt/bootstrap/scripts/verify_image.py` for a low-cost smoke check.
- Resolved stage images are verified with `docker buildx imagetools inspect`.
- A protected package manifest tracks `torch`, `torchvision`, `torchaudio`, `transformers`, `xformers`, `flash-attn`, `triton`, and `sageattention`.
- The optimized stage refreshes the protected package manifest after installing xformers and FlashAttention.
- Custom-node stages verify the manifest after each node install to catch dependency drift early.

## GitHub Actions notes

- Builds are triggered on **GitHub Release** (published) and **manual dispatch**.
- The workflow uses dependent jobs instead of a matrix for the shared chain.
- The final purpose images are independent jobs and run in parallel after `custom-basic`.
- `concurrency` cancels in-progress builds for the same ref.
- Smoke checks are CPU/GPU-driver safe and avoid launching ComfyUI.
