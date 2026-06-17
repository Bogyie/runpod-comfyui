# Build Reference

## Image model

### Stage chain

The build uses the PyTorch Docker Hub image directly as its external base:

```text
pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime
```

Python, CUDA, PyTorch, torchvision, and torchaudio are intentionally inherited from that tag. The workflow does not carry separate Python/CUDA/PyTorch build arguments.

Each stage produces a pushed image. The next dependent job consumes the previous stage through a content-addressed `buildkey-<stage>-<hash>` image tag. If that buildkey image already exists, the job reuses it and only refreshes the run-specific tags.

| Stage | Dockerfile | Adds |
|---|---|---|
| `comfyui` | `docker/Dockerfile.comfyui` | ComfyUI, Transformers, startup scripts, storage helpers |
| `optimized` | `docker/Dockerfile.optimized` | xformers and FlashAttention wheels |
| `runtime-tools` | `docker/Dockerfile.runtime-tools` | supervisord, Caddy, File Browser, Hugging Face CLI, git, curl, wget, runpodctl, GitHub CLI |
| `custom-basic` | `docker/Dockerfile.custom-basic` | ComfyUI-Manager, KJNodes, rgthree-comfy, Crystools |
| `custom-image` | `docker/Dockerfile.custom-image` | controlnet aux, Impact Pack, Sapiens2 Easy, Depth Anything V3 |
| `custom-video` | `docker/Dockerfile.custom-video` | VideoHelperSuite, SeedVR2 Video Upscaler, WanVideoWrapper, LTXVideo |

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

On release, the three final purpose images are also pushed to Docker Hub. `custom-basic` receives the default `latest` alias.

### Image tags

Each stage receives these tags:

| Tag pattern | Example | Scope |
|---|---|---|
| `<stage>` | `custom-image` | all stages |
| `<release-tag>-<stage>` | `v1.0.2-custom-image` | release builds |
| `<base-slug>-cf<comfy>-<stage>` | `2-10-0-cuda12-8-cudnn9-runtime-cf0240-custom-image` | all stages |
| `sha-<hash>-<stage>` | `sha-abc1234-custom-image` | all stages |
| `buildkey-<stage>-<hash>` | `buildkey-custom-image-abc123...` | all stages |

Docker Hub receives these release aliases:

| Tag pattern | Example | Image |
|---|---|---|
| `latest` | `latest` | `custom-basic` |
| `latest-basic` | `latest-basic` | `custom-basic` |
| `<release-tag>-basic` | `v1.0.2-basic` | `custom-basic` |
| `latest-image` | `latest-image` | `custom-image` |
| `<release-tag>-image` | `v1.0.2-image` | `custom-image` |
| `latest-video` | `latest-video` | `custom-video` |
| `<release-tag>-video` | `v1.0.2-video` | `custom-video` |

The base slug is derived from `PYTORCH_BASE_IMAGE`; it is not reconstructed from separate Python/CUDA/PyTorch variables.

## Build arguments

### ComfyUI

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime` | Upstream PyTorch image tag |
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
| `CADDY_VERSION` | `2.11.4` | Caddy version |
| `CADDY_SECURITY_MODULE` | `github.com/greenpau/caddy-security` | AuthCrunch/Caddy security plugin module built into Caddy |
| `FILEBROWSER_VERSION` | `2.63.15` | File Browser version |
| `RUNPODCTL_VERSION` | `2.4.0` | runpodctl version |
| `HUGGINGFACE_HUB_VERSION` | `1.19.0` | Hugging Face Hub CLI package version |
| `FILEBROWSER_LINUX_AMD64_SHA256` | pinned | SHA256 for the Linux amd64 File Browser archive |
| `RUNPODCTL_LINUX_AMD64_SHA256` | pinned | SHA256 for the Linux amd64 runpodctl binary |

### Basic custom nodes

| Name | Default | Purpose |
|---|---|---|
| `BASE_IMAGE` | required | Previous stage image |
| `COMFYUI_MANAGER_REF` | `e4c5401dd5da96e901f8b8cb8a7eca63e13e8ee5` | ComfyUI-Manager git ref |
| `KJNODES_REF` | `8a225698ae7cb87632817419f83a64ecf571fe76` | ComfyUI-KJNodes git ref |
| `RGTHREE_REF` | `738105af5fb14e96fbecaf406dc356e284797e8c` | rgthree-comfy git ref |
| `CRYSTOOLS_REF` | `2f18256c5b5063937106f29a8e0a7db3ae3869b7` | ComfyUI-Crystools git ref |

### Purpose custom nodes

| Name | Default | Purpose |
|---|---|---|
| `CONTROLNET_AUX_REF` | `e8b689a513c3e6b63edc44066560ca5919c0576e` | comfyui_controlnet_aux git ref |
| `IMPACT_PACK_REF` | `429d0159ad429e64d2b3916e6e7be9c22d025c3c` | ComfyUI-Impact-Pack git ref |
| `SAPIENS2_EASY_REF` | `51958bb75a2ee7644018d55b4f2b6f6d535101ad` | ComfyUI-Sapiens2-Easy git ref |
| `DEPTH_ANYTHING_V3_REF` | `6b08cf418dff47430a72e07d0eec8fdb07d464b1` | ComfyUI-DepthAnythingV3 git ref |
| `VIDEO_HELPER_SUITE_REF` | `4ee72c065db22c9d96c2427954dc69e7b908444b` | ComfyUI-VideoHelperSuite git ref |
| `SEEDVR2_VIDEO_UPSCALER_REF` | `4490bd1f482e026674543386bb2a4d176da245b9` | ComfyUI-SeedVR2_VideoUpscaler git ref |
| `WAN_VIDEO_WRAPPER_REF` | `088128b224242e110d3906c6750e9a3a348a659b` | ComfyUI-WanVideoWrapper git ref |
| `LTX_VIDEO_REF` | `229437c6b65796d6a7a63ae34be2bd5ba31fa543` | ComfyUI-LTXVideo git ref |

## Runtime environment variables

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_PORT` | `8188` | ComfyUI port |
| `COMFYUI_HOST` | `127.0.0.1` | ComfyUI bind address behind Caddy |
| `COMFYUI_CORS_ORIGIN` | `*` | ComfyUI CORS origin passed to `--enable-cors-header`; set empty to omit the flag |
| `FILEBROWSER_PORT` | `8080` | File Browser port behind Caddy |
| `FILEBROWSER_HOST` | `127.0.0.1` | File Browser bind address behind Caddy |
| `FILEBROWSER_BASEURL` | `/files` | File Browser URL prefix |
| `FILEBROWSER_ROOT` | `/` | File Browser root; `/` exposes both container storage and the `/workspace` volume |
| `FILEBROWSER_DATABASE` | `/workspace/storage/filebrowser/filebrowser.db` | File Browser persistent database |
| `CADDY_HTTPS_PORT` | `8443` | Public TLS port inside the container |
| `AUTHCRUNCH_AUTH_PATH` | `/auth` | AuthCrunch login path served by Caddy |
| `AUTHCRUNCH_ADMIN_USER` | `runpod` | Initial AuthCrunch local admin username |
| `AUTHCRUNCH_ADMIN_EMAIL` | `runpod@localdomain.local` | Initial AuthCrunch local admin email |
| `AUTHCRUNCH_ADMIN_PASSWORD` | `runpod-comfyui` | Initial AuthCrunch local admin password |
| `AUTHCRUNCH_JWT_SHARED_KEY` | empty | Optional JWT signing key; generated persistently when unset |
| `FILEBROWSER_PROXY_HEADER` | `X-AuthCrunch-User` | Header File Browser trusts for proxy authentication |
| `FILEBROWSER_ADMIN_USER` | `runpod` | File Browser admin user created when missing; should match the AuthCrunch admin username |
| `FILEBROWSER_ADMIN_PASSWORD` | `runpod-comfyui` | Password used only when creating the File Browser admin user |
| `FILEBROWSER_COMMANDS` | `all` | Commands exposed to File Browser's command runner; `all` discovers every executable on `PATH` at startup |
| `FILEBROWSER_SHELL` | `/bin/bash -c` | Shell used by File Browser command execution |
| `CLI_ARGS` | empty | Extra ComfyUI CLI flags |

Leave the RunPod container start command empty. Runtime and final custom images
set Docker
`ENTRYPOINT ["/opt/bootstrap/scripts/runpod-supervisord-entrypoint.sh"]`. The
entrypoint initializes the workspace and generated Caddy config, then runs
supervisord as PID 1 to manage ComfyUI, File Browser, and Caddy. If RunPod is
configured to start `/init`, `s6-overlay-suexec`, or `/opt/bootstrap/start.sh`
as the command, that override bypasses the expected startup path.

## Cache strategy

Each stage has two cache layers:

- Dockerfile-level BuildKit cache mounts for apt and pip work inside the stage.
- Registry cache per stage, for example `cache-comfyui`, `cache-optimized`, and `cache-custom-image`.
- Inline cache metadata in each pushed stage image, so stable tags can act as fallback cache sources.

Every stage job imports cache from the dedicated registry cache, the versioned stage tag, and the stable stage tag. It then pushes its SHA-scoped image, inline cache metadata, and registry cache before downstream jobs start.

Dockerfiles keep expensive install layers before volatile verification and cleanup scripts where possible, so script-only changes avoid reinstalling apt, pip, or custom-node dependencies.

Before building, each job checks whether its `buildkey-<stage>-<hash>` image already exists in GHCR. The hash includes that stage's Dockerfile, relevant build arguments, stage-specific script inputs, and the parent stage build key. On a hit, the job skips Docker build and retags the existing image for the current SHA, stable stage tag, version tag, and release tags.

Script inputs are intentionally scoped by stage:

- `comfyui` hashes only startup and verification scripts used by that image.
- `optimized` hashes only the wheel resolver, CUDA tag helper, cleanup, and verification scripts.
- `runtime-tools` hashes the full `scripts/` tree because it publishes the runtime bootstrap scripts.
- Custom-node stages hash only the install/protected-package scripts they copy directly; inherited runtime scripts are covered by the parent runtime-tools key.

Custom-node refs are pinned to commit SHAs by default. Updating a ref intentionally changes that stage's build key and rebuilds only the affected downstream images.

## Build-time guardrails

- Dockerfiles clean transient files during expensive install layers where possible, then run `/opt/bootstrap/scripts/cleanup-image.sh` before smoke verification.
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
