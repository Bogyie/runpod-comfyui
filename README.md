# runpod-comfyui

Runpod Pod template for ComfyUI with staged Docker images, persistent volume storage, File Browser access, Caddy TLS reverse proxying, purpose-built custom-node variants, and built-in recovery helpers.

## What this image is for

- Start ComfyUI quickly on RunPod
- Expose one TLS- and AuthCrunch-protected TCP port for both ComfyUI and File Browser
- Keep the PyTorch/CUDA/Python stack tied to one upstream PyTorch image tag
- Avoid rebuilding the full stack when only later layers change
- Keep models, outputs, workflows, and most mutable custom nodes on a persistent volume
- Publish separate final images for basic, image, and video workflows

## Staged image chain

The build starts from the upstream PyTorch image:

```text
pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime
```

Each repo-owned step builds and pushes its own image. The SHA-scoped tag from one step becomes the next step's `BASE_IMAGE`.

```text
comfyui -> optimized -> runtime-tools -> custom-basic
                                      -> custom-image
                                      -> custom-video
```

The purpose images are built in parallel after `custom-basic`.

| Stage | Adds |
|---|---|
| `comfyui` | ComfyUI and baseline runtime files |
| `optimized` | xformers and FlashAttention from prebuilt wheels |
| `runtime-tools` | supervisord, Caddy, File Browser, Hugging Face CLI, git, curl, wget, runpodctl, and GitHub CLI |
| `custom-basic` | ComfyUI-Manager, KJNodes, rgthree-comfy, and Crystools |
| `custom-image` | controlnet aux, Impact Pack, Sapiens2 Easy, and Depth Anything V3 |
| `custom-video` | VideoHelperSuite, SeedVR2 Video Upscaler, WanVideoWrapper, and LTXVideo |

Each Dockerfile ends with image cleanup and a low-cost smoke verification.

## Image tags

Image tags include stage tags, release tags, SHA tags, and a slug derived from the PyTorch base image tag plus ComfyUI version.

```text
ghcr.io/bogyie/runpod-comfyui:custom-image
ghcr.io/bogyie/runpod-comfyui:2-10-0-cuda12-8-cudnn9-runtime-cf0240-custom-image
ghcr.io/bogyie/runpod-comfyui:v1.0.2-custom-image
ghcr.io/bogyie/runpod-comfyui:sha-abc1234-custom-image
```

On release, the three final purpose images are also published to Docker Hub:

| Docker Hub tag | Image |
|---|---|
| `latest`, `latest-basic`, `v1.0.2-basic` | `custom-basic` |
| `latest-image`, `v1.0.2-image` | `custom-image` |
| `latest-video`, `v1.0.2-video` | `custom-video` |

Use a pinned release, SHA, or version-slug tag for production templates rather than `latest`.

## Current baseline

- Base image: `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime`
- ComfyUI: `v0.29.2`
- Transformers: `5.14.1`
- xformers: `0.0.35`
- FlashAttention: `2.8.3`
- Supervisor: distro package
- Caddy: `2.11.4`
- File Browser: `2.63.15`
- runpodctl: `2.4.0`
- Hugging Face Hub CLI: `1.26.0`

Python, CUDA, PyTorch, torchvision, and torchaudio come from the PyTorch base image tag, not from separate build arguments.

## Persistent volume

Mount your volume at `/workspace`.

Mutable data stays on the volume:

- models
- outputs
- inputs
- temp files
- user workflows
- user-installed custom nodes
- File Browser database and Caddy/AuthCrunch state
- logs

Main custom node path:

```text
/workspace/storage/custom_nodes
```

Model storage follows the ComfyUI default `models/` layout, and common alias folders such as `unet`, `text_encoders`, and `t2i_adapter` are linked automatically to the matching storage paths.

## Runtime Access

Expose only the Caddy HTTPS port from the RunPod template:

- TCP port `8443` for Caddy TLS

Leave the RunPod container start command empty. The final images start
`/opt/bootstrap/scripts/runpod-supervisord-entrypoint.sh`, which initializes
the workspace and then runs supervisord as PID 1. Do not set the start command
to `/init`, `s6-overlay-suexec`, or `/opt/bootstrap/start.sh`.

Caddy reverse proxies to private localhost services:

- `/` to ComfyUI on `127.0.0.1:8188`
- `/files` to File Browser on `127.0.0.1:8080`

Caddy uses its internal CA for TLS and stores Caddy/AuthCrunch state under `/workspace/storage/caddy`.
Unauthenticated requests to ComfyUI and File Browser are redirected to the AuthCrunch login page at `/auth`.
File Browser uses proxy-header authentication behind Caddy; Caddy writes the authenticated AuthCrunch username to `X-AuthCrunch-User`, and the startup script ensures the matching File Browser admin account exists with command-execution permissions.

Set these environment variables in the RunPod template:

| Name | Default | Purpose |
|---|---|---|
| `CADDY_HTTPS_PORT` | `8443` | Internal Caddy TLS port inside the container |
| `RUNPOD_TCP_PORT_8443` | set by RunPod | Public TCP port mapped to internal port `8443` |
| `CADDY_PUBLIC_PORT` | `RUNPOD_TCP_PORT_8443`, then `8443` | Public TCP port used in startup logs; override only for nonstandard templates |
| `CADDY_PUBLIC_URL` | derived from `RUNPOD_PUBLIC_IP` and public port when available | Public Caddy URL shown in startup logs |
| `CADDY_TLS_SERVER_NAME` | `RUNPOD_PUBLIC_IP`, then `runpod-comfyui.local` | TLS server name/IP Caddy uses for its internal certificate and SNI fallback |
| `AUTHCRUNCH_AUTH_PATH` | `/auth` | AuthCrunch login path served by Caddy |
| `AUTHCRUNCH_ADMIN_USER` | `runpod` | Initial AuthCrunch local admin username |
| `AUTHCRUNCH_ADMIN_EMAIL` | `runpod@localdomain.local` | Initial AuthCrunch local admin email |
| `AUTHCRUNCH_ADMIN_PASSWORD` | `runpod-comfyui` | Initial AuthCrunch local admin password |
| `AUTHCRUNCH_JWT_SHARED_KEY` | empty | Optional JWT signing key; generated persistently when unset |
| `FILEBROWSER_ROOT` | `/` | File Browser root; `/` exposes both container filesystem and the `/workspace` volume |
| `FILEBROWSER_DATABASE` | `/workspace/storage/filebrowser/filebrowser.db` | File Browser database path |
| `FILEBROWSER_PROXY_HEADER` | `X-AuthCrunch-User` | Header File Browser trusts for proxy authentication |
| `FILEBROWSER_ADMIN_USER` | `runpod` | File Browser admin user created when missing; should match the AuthCrunch admin username |
| `FILEBROWSER_ADMIN_PASSWORD` | `runpod-comfyui` | Password used only when creating the File Browser admin user |
| `FILEBROWSER_COMMANDS` | `all` | Commands exposed to File Browser's command runner; `all` discovers every executable on `PATH` at startup |
| `FILEBROWSER_SHELL` | `/bin/bash -c` | Shell used by File Browser command execution |

Use RunPod's [TCP access via public IP](https://docs.runpod.io/pods/configuration/expose-ports#tcp-access-via-public-ip) mode and expose internal container port `8443`. RunPod usually maps that internal port to a different external port; use `RUNPOD_TCP_PORT_8443` or the Direct TCP Ports entry in the Connect menu when building the public URL. Because this bypasses RunPod's HTTP proxy, TLS and auth are handled by Caddy in the container. When connecting by public IP, leave `CADDY_TLS_SERVER_NAME` unset so startup uses `RUNPOD_PUBLIC_IP`, or set it explicitly to the public IP if your template does not provide that variable.

Images built before the supervisord migration used s6-overlay through
`ENTRYPOINT ["/init"]`. If startup fails with
`s6-overlay-suexec: fatal: can only run as pid 1`, redeploy with a newer image
that includes `/opt/bootstrap/scripts/runpod-supervisord-entrypoint.sh`.

## Recovery helpers

Disable a broken node:

```bash
/opt/bootstrap/scripts/disable-node.sh <node-dir>
```

Re-enable it:

```bash
/opt/bootstrap/scripts/enable-node.sh <node-dir>
```

Snapshot the current Python environment:

```bash
/opt/bootstrap/scripts/snapshot-env.sh
```

Restore the baked base environment:

```bash
/opt/bootstrap/scripts/restore-env.sh
```

## More details

- Technical stack and compatibility notes: [docs/technical-details.md](docs/technical-details.md)
- Build arguments and workflow notes: [docs/build-reference.md](docs/build-reference.md)
