# Technical Details

## Current baseline stack

- CUDA `12.8`
- Python `3.11.15`
- PyTorch `2.10.0` with `cu128`
- torchvision `0.25.0`
- torchaudio `2.10.0`
- xformers `0.0.35`
- ComfyUI `v0.19.0`

This image is intentionally aligned to a `CUDA 12.8 + PyTorch 2.10.0 cu128 + Python 3.11.15 + xformers 0.0.35` stack because it is the most practical common baseline for Blackwell-class GPUs such as RTX 5090 and RTX PRO 6000 while remaining suitable for H100.

Before using the image, confirm the host driver is new enough for CUDA 12.8.

## Python

- This image builds CPython `3.11.15` from the upstream Python release tarball instead of relying on Ubuntu's distro Python packages.
- That keeps the interpreter version stable across GitHub Actions runner changes and Ubuntu package updates.
- The virtual environment is created from `/opt/python/current/bin/python3`, so rebuilds preserve the same Python patch version unless you change `PYTHON_VERSION`.
- Python compilation is isolated in a dedicated `python-builder` stage so that changes to ComfyUI refs, scripts, or pip dependencies never trigger a recompilation.

## xformers

- `xformers v0.0.35` publishes support for PyTorch `2.10.0` and later.
- The default image path keeps `CUDA 12.8` and installs `xformers 0.0.35` from the PyTorch `cu128` index so it stays aligned with the selected torch build.
- If the official wheel path gives you trouble on a specific GPU, driver, or custom-node combination, you can rebuild with `--build-arg XFORMERS_INSTALL_MODE=source` as a fallback.
- Keep xformers pinned and install it without dependency resolution so it does not replace your chosen torch build.
- The `slim` image does not change xformers behavior. It only removes recovery-oriented cache files from the final runtime layer.

## Model path normalization

- `/opt/comfy/ComfyUI/models` is linked to `/workspace/storage/models`, so the persistent volume matches ComfyUI's default model root directly.
- Common folder aliases are normalized with symlinks so either naming convention works.
- Current aliases include `diffusion_models -> checkpoints`, `unet -> checkpoints`, `text_encoders -> clip`, and `t2i_adapter -> controlnet`.

## CUDA and driver compatibility

- This template assumes a host driver new enough for CUDA `12.8`.
- Blackwell GPUs such as RTX 5090 and RTX PRO 6000 are the main reason to prefer a `cu128` stack over older CUDA variants.
- This is an inference for the template's stability target: `CUDA 13.0` is newer and supported by PyTorch `2.10.0`, but `CUDA 12.8` is the more conservative shared baseline for H100 plus current Blackwell cards.

## PyTorch behavior changes

- PyTorch `2.6+` changed the default behavior of `torch.load` toward `weights_only=True`.
- Some ComfyUI custom nodes and model loaders still assume the older behavior, so you may see checkpoint-loading regressions in specific nodes even when the base image is healthy.
- When this happens, treat it as a node compatibility issue first, not a signal that the whole CUDA stack is broken.

## Aggressive optimization notes

### Triton

- Triton may be useful for certain PyTorch and ComfyUI optimization paths, but it is not treated as a required baseline dependency in this template.
- A successful Triton install does not guarantee that every ComfyUI optimization path will work cleanly.
- Add it only after validating your target workflow on the GPUs you care about.
- In this repo, Triton is only installed for `aggressive` image variants.

### FlashAttention and other aggressive packages

- Do not bake in `flash-attn` for the first image version.
- It can provide real speedups, but compatibility is more fragile across Python, CUDA, PyTorch, compiler, and GPU combinations.
- If you want it later, prefer a second image flavor instead of changing the main stable image.

### SageAttention

- `sageattention` is limited to `aggressive` image variants.
- Benefits on Blackwell or H100 may be limited depending on workload.
- Treat it as an experiment, not a guaranteed speedup.

## Node pack caveats

- Several baked custom nodes bring substantial Python dependencies of their own.
- This improves out-of-the-box usability, but it also means upstream node changes can affect image build stability more than before.
- `manager-only` variants reduce that surface area and are a good choice for stricter production templates.
- This repo uses `Civicomfy` as the default Civitai integration node because its documented workflow fits PV-backed cloud setups well.
- For production use, you will likely want to pin ComfyUI and baked node repos to specific commits after your first validation pass.
