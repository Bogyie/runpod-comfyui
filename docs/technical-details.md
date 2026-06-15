# Technical Details

## Current baseline stack

- CUDA `12.8`
- Python `3.11.15`
- PyTorch `2.10.0` with `cu128`
- torchvision `0.25.0`
- torchaudio `2.10.0`
- Transformers `5.12.0`
- xformers `0.0.35`
- FlashAttention `2.8.3`
- ComfyUI `v0.24.0`

This image is aligned to a `CUDA 12.8 + PyTorch 2.10.0 cu128 + Python 3.11.15` stack for Blackwell-class GPUs such as RTX 5090 and RTX PRO 6000 while remaining suitable for H100.

Before using the image, confirm the host driver is new enough for CUDA 12.8.

## Compatibility checks

- ComfyUI `v0.24.0` declares Python `>=3.10`, so Python `3.11.15` is within range.
- Transformers `5.12.0` declares Python `3.10+` and PyTorch `2.4+`, so PyTorch `2.10.0` is within range.
- xformers `0.0.35` declares `torch>=2.10`, matching the pinned torch version.
- FlashAttention requires CUDA `12.0+` and PyTorch `2.2+`; the current stack uses CUDA `12.8` and PyTorch `2.10.0`.

## Python

- This image builds CPython `3.11.15` from the upstream Python release tarball instead of relying on Ubuntu's distro Python packages.
- That keeps the interpreter version stable across GitHub Actions runner changes and Ubuntu package updates.
- Python compilation is isolated in `docker/Dockerfile.core`, so later stage changes do not trigger a Python rebuild.

## Stage details

### Core

The core image installs:

- ComfyUI `v0.24.0`
- PyTorch, torchvision, and torchaudio from the CUDA 12.8 PyTorch wheel index
- Transformers `5.12.0`
- `ComfyUI-Manager`

The core image captures the first protected package manifest.

### Runtime tools

The runtime tools image adds operational tooling:

- `huggingface_hub[cli]`
- `runpodctl`
- `wget`
- `jq`
- SSH client
- `code-server`

This stage is separate so operational tool changes do not rebuild ComfyUI or PyTorch.

### Optimized

The optimized image adds:

- xformers `0.0.35`
- FlashAttention `2.8.3`

FlashAttention can be expensive to compile. Keeping it in a separate stage isolates that cost from core runtime and custom-node changes.

### Custom nodes

Only two baked custom nodes are included:

- Basic: `kijai/ComfyUI-KJNodes`
- Advanced: `Bogyie/ComfyUI-Sapiens2-Easy`

The previous broad baked-node pack was removed. This reduces dependency drift and narrows the rebuild surface.

## Model path normalization

- `/opt/comfy/ComfyUI/models` is linked to `/workspace/storage/models`, so the persistent volume matches ComfyUI's default model root directly.
- Common folder aliases are normalized with symlinks so either naming convention works.
- Current aliases include `unet -> diffusion_models`, `text_encoders -> clip`, and `t2i_adapter -> controlnet`.

## PyTorch behavior changes

- PyTorch `2.6+` changed the default behavior of `torch.load` toward `weights_only=True`.
- Some ComfyUI custom nodes and model loaders still assume the older behavior, so checkpoint-loading regressions can still appear in specific nodes even when the base image is healthy.

## Guardrails

- Protected package drift is checked during build.
- The guarded package set includes torch, torchvision, torchaudio, transformers, xformers, flash-attn, triton, and sageattention.
- Custom-node stages verify that node requirements did not replace those packages unexpectedly.
