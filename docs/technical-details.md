# Technical Details

## Current baseline

- Base image: `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel`
- ComfyUI: `v0.24.0`
- Transformers: `5.12.0`
- xformers: `0.0.35`
- FlashAttention: `2.8.3`

Python, CUDA, PyTorch, torchvision, and torchaudio come from the PyTorch base image tag. Changing that tag is the intended way to move the low-level ML stack.

Before using the image, confirm the host driver is new enough for the CUDA runtime provided by the selected PyTorch image.

## Compatibility checks

- ComfyUI `v0.24.0` declares Python `>=3.10`.
- Transformers `5.12.0` declares Python `3.10+` and PyTorch `2.4+`.
- xformers is installed from the PyTorch CUDA wheel index derived from the selected PyTorch base image.
- FlashAttention is installed from the mjunya prebuilt wheel releases; the build fails before compiling if no matching wheel exists.

## Python environment

The image creates `/opt/comfy/venv` from the Python interpreter shipped by the PyTorch base image with `--system-site-packages`, so the venv can use the base image's torch installation without reinstalling PyTorch.

The helper scripts keep the historical `COMFY_VENV` name, and its default value remains `/opt/comfy/venv`.

## Stage details

### ComfyUI

The ComfyUI image installs:

- ComfyUI `v0.24.0`
- Transformers `5.12.0`
- startup and recovery scripts
- storage initialization helpers

It captures the first protected package manifest after ComfyUI dependencies are installed.

### Optimized

The optimized image adds:

- xformers `0.0.35`
- FlashAttention `2.8.3`

Both installs require binary wheels. FlashAttention wheel selection is dynamic and based on the currently installed Python ABI, torch version, CUDA version, and architecture.

### Runtime tools

The runtime tools image adds:

- `huggingface_hub[cli]`
- git
- curl
- wget
- runpodctl
- GitHub CLI
- code-server

### Basic custom nodes

The basic custom-node image adds:

- `Comfy-Org/ComfyUI-Manager`
- `kijai/ComfyUI-KJNodes`
- `rgthree/rgthree-comfy`
- `crystian/ComfyUI-Crystools`

### Purpose custom nodes

The final purpose images split advanced nodes by workflow:

- `custom-image`: `Fannovel16/comfyui_controlnet_aux`, `ltdrdata/ComfyUI-Impact-Pack`, `Bogyie/ComfyUI-Sapiens2-Easy`, `PozzettiAndrea/ComfyUI-DepthAnythingV3`
- `custom-video`: `kosinkadink/ComfyUI-VideoHelperSuite`, `numz/ComfyUI-SeedVR2_VideoUpscaler`, `kijai/ComfyUI-WanVideoWrapper`, `Lightricks/ComfyUI-LTXVideo`

## Model path normalization

- `/opt/comfy/ComfyUI/models` is linked to `/workspace/storage/models`, so the persistent volume matches ComfyUI's default model root directly.
- Common folder aliases are normalized with symlinks so either naming convention works.
- Current aliases include `unet -> diffusion_models`, `text_encoders -> clip`, and `t2i_adapter -> controlnet`.

## Guardrails

- Protected package drift is checked during build.
- The guarded package set includes torch, torchvision, torchaudio, transformers, xformers, flash-attn, triton, and sageattention.
- Custom-node stages verify that node requirements did not replace those packages unexpectedly.
- Each image removes apt lists, pip caches, `.git` directories, and Python bytecode before running a final smoke verification.
