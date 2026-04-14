# runpod-comfyui

Runpod Pod template for ComfyUI with a fast startup path, persistent volume storage, baked-in baseline custom nodes, and an included code-server.

## Goals

- Launch the ComfyUI web UI quickly.
- Keep models, outputs, workflows, and most custom nodes on a persistent volume.
- Bake in a small, stable set of baseline dependencies so recovery is easy.
- Target modern NVIDIA GPUs including RTX 5090, H100, and RTX PRO 6000.

## Image contents

The image is designed to keep the runtime stable and the mutable data outside the container.

### Baked into the image

- CUDA 12.8 base image
- Python 3.11 virtual environment
- PyTorch 2.7.1 with `cu128`
- `xformers`
- ComfyUI
- `ComfyUI-Manager`
- `ComfyUI-Impact-Pack`
- `code-server`
- Recovery scripts in `/opt/bootstrap/scripts`

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
- `ComfyUI-Impact-Pack`

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

## Build arguments

These let you pin upstream repos during image builds.

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_REF` | `master` | ComfyUI git ref |
| `COMFYUI_MANAGER_REF` | `main` | ComfyUI-Manager git ref |
| `IMPACT_PACK_REF` | `main` | Impact Pack git ref |
| `CODE_SERVER_VERSION` | `4.103.2` | code-server version |
| `PYTHON_VERSION` | `3.11` | Python minor version |

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

The workflow in [docker.yml](/Users/dev/repo/github/bogyie/runpod-comfyui/.github/workflows/docker.yml) builds the image with Buildx and publishes it to GHCR on pushes to `main` and version tags.

Default image name:

```text
ghcr.io/<github-owner>/runpod-comfyui
```

Recommended Runpod template practice:

- Point the template to a pinned image tag, not `latest`.
- Promote a tested version tag after validation on your target GPUs.
- Keep the persistent volume mounted at `/workspace`.

## Notes on GPU compatibility

This image is intentionally aligned to a `CUDA 12.8 + PyTorch cu128` stack because it is the most natural baseline for Blackwell-class GPUs such as RTX 5090 and RTX PRO 6000 while remaining suitable for H100.

Before using the image, confirm the host driver is new enough for CUDA 12.8.

## Next steps

Good follow-up improvements after the first working image:

- Pin known-good git commits for ComfyUI and the baked-in custom nodes.
- Add a healthcheck script that verifies `8188` and `8080`.
- Add optional helper scripts for downloading from Civitai or Hugging Face into the PV.
- Add a second image flavor if you later want a more conservative compatibility stack.
