# runpod-comfyui

Runpod Pod template for ComfyUI with fast startup, persistent volume storage, baked-in baseline custom nodes, and built-in `code-server`.

## What this image is for

- Start ComfyUI quickly on Runpod
- Keep models, outputs, workflows, and most custom nodes on a persistent volume
- Bake in a stable baseline so recovery is easy
- Support modern NVIDIA GPUs such as RTX 5090, H100, and RTX PRO 6000

## Recommended image variants

- `stable-default-aggr`
  Recommended default. Includes the default baked node pack and aggressive optimization extras.
- `stable-default-safe`
  Same baked node pack, but without aggressive optimization extras.
- `stable-manager-aggr`
  Smaller baked node set with aggressive optimization extras.
- `stable-manager-safe`
  Smallest stable baseline. Good when you want most nodes managed on the volume.

Image tags (example for release `v1.0.2`):

```text
ghcr.io/bogyie/runpod-comfyui:latest
ghcr.io/bogyie/runpod-comfyui:v1.0.2
ghcr.io/bogyie/runpod-comfyui:v1.0.2-stable-default-aggr
ghcr.io/bogyie/runpod-comfyui:py311-pt210-cu128-cf019-stable-default-aggr
ghcr.io/bogyie/runpod-comfyui:stable-default-aggr
```

Use a pinned release or version-slug tag for production templates rather than `latest`.

## Included in the image

- ComfyUI
- `ComfyUI-Manager`
- `code-server`
- Recovery scripts in `/opt/bootstrap/scripts`

Default baked custom node pack:

- `comfyui_controlnet_aux`
- `Civicomfy`
- `ComfyUI_IPAdapter_plus`
- `ComfyUI-GGUF`
- `ComfyUI-Impact-Pack`
- `ComfyUI-SAM3`
- `rgthree-comfy`
- `ComfyUI-Easy-Use`
- `ComfyUI-KJNodes`

Optional baked node:

- `ComfyUI-WanVideoWrapper`

## Persistent volume

Mount your volume at `/workspace`.

Mutable data stays on the volume:

- models
- outputs
- inputs
- temp files
- user workflows
- user-installed custom nodes
- code-server user data
- logs

Main custom node path:

```text
/workspace/storage/custom_nodes
```

Model storage also follows the ComfyUI default `models/` layout, and common alias folders such as `diffusion_models`, `unet`, `text_encoders`, and `t2i_adapter` are linked automatically to the matching storage paths.

## Ports

- `8188` for ComfyUI
- `8080` for `code-server`

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
