# Build Reference

## Image model

The repository publishes exactly two final images:

| Variant | Optimization stage | Contents |
|---|---|---|
| `basic` | `optimized` | ComfyUI, runtime tools, four Basic custom nodes, xformers, and FlashAttention |
| `basic-unoptimized` | `unoptimized` | The same runtime and custom nodes without xformers or FlashAttention |

Both variants are built from `docker/Dockerfile.basic`. Its internal multi-stage layout shares the ComfyUI and runtime layers, but intermediate stages are not pushed as images.

```text
                        -> unoptimized --\
pytorch -> comfyui ----                    -> runtime-tools -> basic
                        -> optimized ----/
```

Python, CUDA, PyTorch, torchvision, and torchaudio are inherited from the `PYTORCH_BASE_IMAGE` value in `docker.env`.

## Version configuration

[`docker.env`](../docker.env) is the single source of truth for all build-time versions and custom-node refs. The Dockerfile declares build arguments without embedding version defaults. GitHub Actions loads the same file before each matrix build, and the local build helper exports it before invoking Docker.

ComfyUI uses a stable release tag. Custom nodes are pinned to exact commit SHAs from their upstream default branches so builds remain reproducible.

| Variable group | Variables |
|---|---|
| Base and ComfyUI | `PYTORCH_BASE_IMAGE`, `COMFYUI_REF`, `TRANSFORMERS_VERSION` |
| Optimization | `XFORMERS_VERSION`, `FLASH_ATTN_VERSION` |
| Runtime tools | `CADDY_VERSION`, `CADDY_SECURITY_MODULE`, `FILEBROWSER_VERSION`, `RUNPODCTL_VERSION`, `HUGGINGFACE_HUB_VERSION` |
| Download integrity | `FILEBROWSER_LINUX_AMD64_SHA256`, `RUNPODCTL_LINUX_AMD64_SHA256` |
| Basic custom nodes | `COMFYUI_MANAGER_REF`, `KJNODES_REF`, `RGTHREE_REF`, `CRYSTOOLS_REF` |

When updating File Browser or runpodctl, update its SHA256 in the same `docker.env` change.

## Local builds

The helper loads `docker.env` and forwards every build argument:

```bash
bash .github/scripts/build-local.sh basic --load
bash .github/scripts/build-local.sh basic-unoptimized --load
```

Extra `docker buildx build` options can be appended after the variant.
Both CI and the helper target `linux/amd64`, matching RunPod's NVIDIA GPU hosts and the selected PyTorch base image.

## Image tags

Each GitHub Actions run assigns these GHCR tags to one of the two final images:

| Pattern | Example |
|---|---|
| `<variant>` | `basic-unoptimized` |
| `<release>-<variant>` | `v1.0.2-basic-unoptimized` |
| `<base-slug>-cf<comfy>-<variant>` | `2-10-0-cuda12-8-cudnn9-runtime-cf0331-basic` |
| `sha-<sha>-<variant>` | `sha-abc1234-basic` |
| `buildkey-<variant>-<hash>` | `buildkey-basic-unoptimized-abc123...` |

On releases, Docker Hub receives:

| Tags | Variant |
|---|---|
| `latest`, `latest-basic`, `<release>-basic` | `basic` |
| `latest-basic-unoptimized`, `<release>-basic-unoptimized` | `basic-unoptimized` |

The existing `latest` and `latest-basic` aliases remain on the optimized `basic` image for compatibility with earlier releases.

## Cache strategy

- BuildKit cache mounts retain apt and pip downloads inside the multi-stage build.
- Each variant has its own registry cache: `cache-basic` and `cache-basic-unoptimized`.
- A build key covers the selected variant, its version inputs, `docker/Dockerfile.basic`, startup files, runtime scripts, and root filesystem files.
- When a matching build-key image already exists, the workflow retags it instead of rebuilding.
- Optimization package versions affect only the optimized `basic` build key.

## Build-time guardrails

- Required build arguments fail immediately when missing.
- Downloaded File Browser and runpodctl binaries are checked against pinned SHA256 values.
- The protected package manifest tracks torch, torchvision, torchaudio, transformers, xformers, flash-attn, triton, and sageattention.
- The optimized path refreshes that manifest after installing xformers and FlashAttention.
- Each custom node install verifies that its requirements did not replace protected packages unexpectedly.
- The final stage removes apt lists, pip caches, `.git` directories, and Python bytecode before smoke verification.

## Runtime environment variables

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_PORT` | `8188` | ComfyUI port |
| `COMFYUI_HOST` | `127.0.0.1` | ComfyUI bind address behind Caddy |
| `COMFYUI_CORS_ORIGIN` | `*` | ComfyUI CORS origin; set empty to omit the flag |
| `FILEBROWSER_PORT` | `8080` | File Browser port behind Caddy |
| `FILEBROWSER_HOST` | `127.0.0.1` | File Browser bind address behind Caddy |
| `FILEBROWSER_BASEURL` | `/files` | File Browser URL prefix |
| `FILEBROWSER_ROOT` | `/` | File Browser root |
| `FILEBROWSER_DATABASE` | `/workspace/storage/filebrowser/filebrowser.db` | Persistent File Browser database |
| `CADDY_HTTPS_PORT` | `8443` | Internal Caddy TLS port |
| `RUNPOD_TCP_PORT_8443` | set by RunPod | Public TCP port mapped to `8443` |
| `CADDY_PUBLIC_PORT` | RunPod port, then `8443` | Public port shown in startup logs |
| `CADDY_PUBLIC_URL` | derived | Public Caddy URL shown in startup logs |
| `CADDY_TLS_SERVER_NAME` | RunPod public IP, then local name | Internal certificate and SNI name |
| `AUTHCRUNCH_AUTH_PATH` | `/auth` | AuthCrunch login path |
| `AUTHCRUNCH_ADMIN_USER` | `runpod` | Initial AuthCrunch admin username |
| `AUTHCRUNCH_ADMIN_EMAIL` | `runpod@localdomain.local` | Initial AuthCrunch admin email |
| `AUTHCRUNCH_ADMIN_PASSWORD` | `runpod-comfyui` | Initial AuthCrunch admin password |
| `AUTHCRUNCH_JWT_SHARED_KEY` | empty | Optional persistent JWT signing key |
| `FILEBROWSER_PROXY_HEADER` | `X-AuthCrunch-User` | Trusted proxy authentication header |
| `FILEBROWSER_ADMIN_USER` | `runpod` | File Browser admin username |
| `FILEBROWSER_ADMIN_PASSWORD` | `runpod-comfyui` | Initial File Browser password |
| `FILEBROWSER_COMMANDS` | `all` | Commands exposed by File Browser |
| `FILEBROWSER_SHELL` | `/bin/bash -c` | File Browser command shell |
| `CLI_ARGS` | empty | Extra ComfyUI CLI flags |

Leave the RunPod container start command empty. Both final images use `/opt/bootstrap/scripts/runpod-supervisord-entrypoint.sh` as PID 1.

## GitHub Actions

- Builds run on a published GitHub Release or manual dispatch.
- A two-entry matrix builds `basic` and `basic-unoptimized` in parallel.
- Only those two final variants are pushed; internal Dockerfile stages remain build layers.
- `concurrency` cancels an older in-progress build for the same ref.
- Smoke checks avoid launching ComfyUI and do not require a GPU driver.
