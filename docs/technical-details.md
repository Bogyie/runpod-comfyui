# Technical Details

## Current baseline

- Base image: `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime`
- ComfyUI: `v0.33.1`
- Transformers: `5.14.1`
- xformers: `0.0.35`
- FlashAttention: `2.8.3`
- Supervisor: distro package
- Caddy: `2.11.4`
- File Browser: `2.63.15`

Python, CUDA, PyTorch, torchvision, and torchaudio come from the PyTorch base image tag. Changing that tag is the intended way to move the low-level ML stack.

Before using the image, confirm the host driver is new enough for the CUDA runtime provided by the selected PyTorch image.

## Compatibility checks

- ComfyUI `v0.33.1` is installed from its stable release tag and its published requirements file.
- Transformers `5.14.1` declares Python `3.10+` and PyTorch `2.4+`.
- xformers `0.0.35` stable wheels require PyTorch `2.10.0`, so the base image remains on that PyTorch release.
- xformers is installed from the PyTorch CUDA wheel index derived from the selected PyTorch base image.
- FlashAttention is installed from the mjunya prebuilt wheel releases; the build fails before compiling if no matching wheel exists.

## Python environment

The image creates `/opt/comfy/venv` from the Python interpreter shipped by the PyTorch base image with `--system-site-packages`, so the venv can use the base image's torch installation without reinstalling PyTorch.

The helper scripts keep the historical `COMFY_VENV` name, and its default value remains `/opt/comfy/venv`.

## Build details

### ComfyUI

The shared ComfyUI stage installs:

- ComfyUI `v0.33.1`
- Transformers `5.14.1`
- startup and recovery scripts
- storage initialization helpers

It captures the first protected package manifest after ComfyUI dependencies are installed.

### Optimized

The optional optimized stage adds:

- xformers `0.0.35`
- FlashAttention `2.8.3`

Both installs require binary wheels. FlashAttention wheel selection is dynamic and based on the currently installed Python ABI, torch version, CUDA version, and architecture.

### Runtime tools

The shared runtime-tools stage adds:

- supervisord
- Caddy
- File Browser
- `huggingface_hub` (including the `hf` CLI)
- git
- curl
- wget
- runpodctl
- GitHub CLI

Final images use `/opt/bootstrap/scripts/runpod-supervisord-entrypoint.sh` as
Docker entrypoint. It runs the workspace/Caddy initialization script and then
execs supervisord as PID 1. supervisord starts ComfyUI, File Browser, and
Caddy as foreground services, with no inherited Docker `CMD` so ComfyUI is not
started twice. The RunPod container start command must stay empty; overriding
it bypasses the expected startup path. Caddy listens on internal container port
`8443/tcp`; RunPod maps that to a public TCP port exposed as
`RUNPOD_TCP_PORT_8443` and in the Direct TCP Ports entry in the Connect menu.
Caddy terminates TLS with Caddy's internal CA. Startup uses
`CADDY_TLS_SERVER_NAME`, defaulting to `RUNPOD_PUBLIC_IP` when available, as the
managed internal certificate name and Caddy's `default_sni`/`fallback_sni`
target so IP-based clients and clients without SNI can still complete the TLS
handshake. Caddy serves the AuthCrunch login portal at `/auth`, authorizes
ComfyUI and File Browser requests with AuthCrunch tokens, serves HTTP/1.1 and
HTTP/2 over TCP, and proxies `/` to ComfyUI and `/files` to File Browser.

File Browser stores its database under `/workspace/storage/filebrowser` by default. Its default root is `/`, so it can browse both the container filesystem and the mounted RunPod `/workspace` volume. It uses proxy-header authentication behind Caddy: Caddy authorizes the request with AuthCrunch, writes the authenticated username to `X-AuthCrunch-User`, and File Browser trusts that header. Startup creates or updates the matching File Browser admin account with command-execution permissions. Set `FILEBROWSER_ROOT=/workspace` if you want to restrict it to persistent volume data only.

### Basic custom nodes

Both final images add:

- `Comfy-Org/ComfyUI-Manager`
- `kijai/ComfyUI-KJNodes`
- `rgthree/rgthree-comfy`
- `crystian/ComfyUI-Crystools`

The `basic` variant reaches the runtime stage through the xformers/FlashAttention branch, preserving the previous default image behavior. The `basic-unoptimized` variant reaches the same runtime and custom-node stages through the unoptimized branch. Only the two final variants are pushed.

## Model path normalization

- `/opt/comfy/ComfyUI/models` is linked to `/workspace/storage/models`, so the persistent volume matches ComfyUI's default model root directly.
- Common folder aliases are normalized with symlinks so either naming convention works.
- Current aliases include `unet -> diffusion_models`, `text_encoders -> clip`, and `t2i_adapter -> controlnet`.

## Guardrails

- Protected package drift is checked during build.
- The guarded package set includes torch, torchvision, torchaudio, transformers, xformers, flash-attn, triton, and sageattention.
- Custom-node installation verifies that node requirements did not replace those packages unexpectedly.
- Each final image removes apt lists, pip caches, `.git` directories, and Python bytecode before running a smoke verification.
