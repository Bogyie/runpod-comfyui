# runpod-comfyui

Runpod Pod template for ComfyUI with a fast startup path, persistent volume storage, baked-in baseline custom nodes, and an included code-server.

## Goals

- Launch the ComfyUI web UI quickly.
- Keep models, outputs, workflows, and most custom nodes on a persistent volume.
- Bake in a small, stable set of baseline dependencies so recovery is easy.
- Target modern NVIDIA GPUs including RTX 5090, H100, and RTX PRO 6000.

## Image contents

The image is designed to keep the runtime stable and the mutable data outside the container.

### Image variants

- `stable`: includes the recovery-friendly wheel cache in `/opt/wheels` and is the recommended default for daily use.
- `slim`: removes the wheel cache to shrink the runtime image size while keeping the same runtime behavior.
- `default-pack`: includes the full default baked custom node set.
- `manager-only`: keeps only `ComfyUI-Manager` baked in and leaves the rest to the persistent volume.
- `safe`: keeps the base runtime conservative.
- `aggressive`: adds experimental optimization packages on top of the base runtime.

### Baked into the image

- CUDA 12.8 base image
- Python 3.11 virtual environment
- PyTorch 2.7.1 with `cu128`
- `xformers` with a selectable install mode
- ComfyUI
- `ComfyUI-Manager`
- `code-server`
- Recovery scripts in `/opt/bootstrap/scripts`

### Baked custom nodes in all image variants

- `ComfyUI-Manager`

### Default custom node pack

Included when `INCLUDE_DEFAULT_CUSTOM_NODE_PACK=1`:

- `comfyui_controlnet_aux`
- `Civicomfy`
- `ComfyUI_IPAdapter_plus`
- `ComfyUI-GGUF`
- `ComfyUI-Impact-Pack`
- `ComfyUI-SAM3`
- `rgthree-comfy`
- `ComfyUI-Easy-Use`
- `ComfyUI-KJNodes`

### Stable-only extras

- Wheel cache in `/opt/wheels` for faster environment restoration

### Optional baked custom nodes

- `ComfyUI-WanVideoWrapper`
  Enable with `--build-arg INCLUDE_WAN_VIDEO_WRAPPER=1`

### Aggressive optimization extras

Included when `ENABLE_AGGRESSIVE_OPTIMIZATIONS=1`:

- `triton`
- `sageattention`

### Kept on the persistent volume

- Models
- Outputs
- Inputs
- Temp files
- User workflows
- User-installed custom nodes

## Why this layout

This template separates the stable base environment from user-managed assets:

- The image contains the known-good CUDA, PyTorch, and baseline node setup.
- The persistent volume keeps your models and experimental nodes across container rebuilds.
- If a user-installed node breaks ComfyUI, you can disable that node without rebuilding the image.

## Ports

- `8188`: ComfyUI web UI
- `8080`: code-server

## Persistent volume layout

Mount your volume at `/workspace`.

```text
/workspace/
  code-server/
  logs/
  state/
    snapshots/
  storage/
    custom_nodes/
    custom_nodes.disabled/
    input/
    output/
    temp/
    user/
    models/
      checkpoints/
      clip/
      clip_vision/
      configs/
      controlnet/
      diffusers/
      embeddings/
      gligen/
      hypernetworks/
      loras/
      style_models/
      unet/
      upscale_models/
      vae/
```

## Custom node strategy

### Baseline nodes

These are installed into the image:

- `ComfyUI-Manager`
- `ComfyUI-Impact-Pack` if `INCLUDE_DEFAULT_CUSTOM_NODE_PACK=1`

Use this for nodes you expect to need almost every time and do not want to reinstall on every pod.

### User nodes

Install experimental or fast-moving nodes into:

```text
/workspace/storage/custom_nodes
```

If a node breaks startup, move it out of the way:

```bash
/opt/bootstrap/scripts/disable-node.sh <node-dir>
```

To re-enable it later:

```bash
/opt/bootstrap/scripts/enable-node.sh <node-dir>
```

## Environment recovery

Take a snapshot of the current Python package state:

```bash
/opt/bootstrap/scripts/snapshot-env.sh
```

Restore the base image Python environment:

```bash
/opt/bootstrap/scripts/restore-env.sh
```

This restores from the baked-in lock file. It is meant to recover the base environment quickly if package changes drift.

## Build-time guardrails

The image build protects the core runtime stack while baked custom nodes are being installed.

- A protected package manifest is captured after the base `torch/torchvision/torchaudio/xformers` install.
- After each baked custom node install step, the build verifies that critical packages have not drifted.
- The guarded package set currently includes `torch`, `torchvision`, `torchaudio`, `xformers`, `triton`, and `sageattention`.
- If a custom node install changes one of those packages unexpectedly, the Docker build fails instead of producing a silently polluted image.
- `aggressive` variants intentionally install `triton` and `sageattention`, then refresh the protected manifest after that step.

## Build arguments

These let you pin upstream repos during image builds.

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_REF` | `v0.12.3` | ComfyUI git ref |
| `COMFYUI_MANAGER_REF` | `main` | ComfyUI-Manager git ref |
| `IMPACT_PACK_REF` | `main` | Impact Pack git ref |
| `WAN_VIDEO_WRAPPER_REF` | `main` | WanVideoWrapper git ref |
| `CODE_SERVER_VERSION` | `4.103.2` | code-server version |
| `PYTHON_VERSION` | `3.11` | Python minor version |
| `XFORMERS_INSTALL_MODE` | `wheel` | `wheel` for faster builds, `source` for Blackwell fallback |
| `INCLUDE_DEFAULT_CUSTOM_NODE_PACK` | `1` | Set to `0` to bake only `ComfyUI-Manager` |
| `INCLUDE_WAN_VIDEO_WRAPPER` | `0` | Set to `1` to bake in WanVideoWrapper |
| `ENABLE_AGGRESSIVE_OPTIMIZATIONS` | `0` | Set to `1` to install experimental optimization packages |
| `TRITON_VERSION` | `3.6.0` | Triton version for aggressive builds |
| `SAGEATTENTION_VERSION` | `0.1.0` | SageAttention version for aggressive builds |

## Runtime environment variables

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_PORT` | `8188` | ComfyUI port |
| `CODE_SERVER_PORT` | `8080` | code-server port |
| `COMFYUI_HOST` | `0.0.0.0` | ComfyUI bind address |
| `CODE_SERVER_HOST` | `0.0.0.0` | code-server bind address |
| `CODE_SERVER_AUTH` | `none` | code-server auth mode |
| `CLI_ARGS` | empty | Extra ComfyUI CLI flags |

## GitHub Actions image build

The workflow in [docker.yml](/Users/dev/repo/github/bogyie/runpod-comfyui/.github/workflows/docker.yml) builds the full matrix across `stable/slim`, `default-pack/manager-only`, and `safe/aggressive` with Buildx and publishes them to GHCR on pushes to `main` and version tags.

Default image name:

```text
ghcr.io/<github-owner>/runpod-comfyui
```

Recommended Runpod template practice:

- Point the template to a pinned image tag, not `latest-*`.
- Promote a tested version tag after validation on your target GPUs.
- Keep the persistent volume mounted at `/workspace`.
- Use `stable` first unless you know you do not need the baked wheel cache.
- Use `manager-only` when you want the smallest and most controllable baked node set.
- Treat `aggressive` variants as experimental until you validate them on your target GPUs and workflows.

Example tags:

```text
ghcr.io/<github-owner>/runpod-comfyui:latest-stable-default-pack-safe
ghcr.io/<github-owner>/runpod-comfyui:latest-stable-default-pack-aggressive
ghcr.io/<github-owner>/runpod-comfyui:latest-stable-manager-only-safe
ghcr.io/<github-owner>/runpod-comfyui:latest-slim-manager-only-safe
ghcr.io/<github-owner>/runpod-comfyui:v0.1.0-stable-default-pack-safe
```

## Notes on GPU compatibility

This image is intentionally aligned to a `CUDA 12.8 + PyTorch cu128` stack because it is the most natural baseline for Blackwell-class GPUs such as RTX 5090 and RTX PRO 6000 while remaining suitable for H100.

Before using the image, confirm the host driver is new enough for CUDA 12.8.

## Compatibility notes

### Python

- Python `3.11` is the default because it is broadly supported by the current PyTorch and xformers releases while staying conservative for ComfyUI custom nodes.
- Avoid moving to Python `3.12+` until your must-have custom nodes have been validated against it.

### CUDA and driver compatibility

- This template assumes a host driver new enough for CUDA `12.8`.
- Blackwell GPUs such as RTX 5090 and RTX PRO 6000 are the main reason to prefer a `cu128` stack over older CUDA variants.
- If you later decide to support older environments first, it is better to publish a separate compatibility image than to weaken the main Blackwell-ready image.

### PyTorch behavior changes

- PyTorch `2.6+` changed the default behavior of `torch.load` toward `weights_only=True`.
- Some ComfyUI custom nodes and model loaders still assume the older behavior, so you may see checkpoint-loading regressions in specific nodes even when the base image is healthy.
- When this happens, treat it as a node compatibility issue first, not a signal that the whole CUDA stack is broken.

### xformers

- The image defaults to `XFORMERS_INSTALL_MODE=wheel` because it builds faster.
- On some Blackwell systems, especially RTX 5090, prebuilt xformers wheels have been reported to fail at runtime with kernel compatibility errors.
- If that happens, rebuild the image with `--build-arg XFORMERS_INSTALL_MODE=source`. This is slower to build but is often a better fallback for new GPU architectures.
- Keep xformers pinned and install it without dependency resolution so it does not replace your chosen torch build.
- The `slim` image does not change xformers behavior. It only removes recovery-oriented cache files from the final runtime layer.

### Triton

- Triton may be useful for certain PyTorch and ComfyUI optimization paths, but it is not treated as a required baseline dependency in this template.
- A successful Triton install does not guarantee that every ComfyUI optimization path will work cleanly.
- Add it only after validating your target workflow on the GPUs you care about.
- In this repo, Triton is only installed for `aggressive` image variants.

### FlashAttention and other aggressive optimization packages

- Do not bake in `flash-attn` for the first image version.
- It can provide real speedups, but compatibility is more fragile across Python, CUDA, PyTorch, compiler, and GPU combinations.
- If you want it later, prefer a second image flavor such as `aggressive-optimizations` instead of changing the base stable image.

### SageAttention

- `sageattention` is also limited to `aggressive` image variants.
- Its project notes say current performance tuning is strongest on RTX 4090 and RTX 3090, so benefits on Blackwell or H100 may be limited.
- Treat it as an experiment, not a guaranteed speedup.

### Node pack caveat

- Several baked custom nodes bring substantial Python dependencies of their own.
- This improves out-of-the-box usability, but it also means upstream node changes can affect image build stability more than before.
- `manager-only` variants reduce that surface area and are a good choice for stricter production templates.
- This repo uses `Civicomfy` as the default Civitai integration node because its documented workflow fits PV-backed cloud setups well, including Runpod-style storage roots.
- For production use, you will likely want to pin these repos to specific commits once you finish your first validation pass.

## Next steps

Good follow-up improvements after the first working image:

- Pin known-good git commits for ComfyUI and the baked-in custom nodes.
- Add a healthcheck script that verifies `8188` and `8080`.
- Add optional helper scripts for downloading from Civitai or Hugging Face into the PV.
- Add a second image flavor if you later want a more conservative compatibility stack.
- Add an alternate optimized image once you have validated `xformers source build`, Triton, or FlashAttention on your target GPUs.
