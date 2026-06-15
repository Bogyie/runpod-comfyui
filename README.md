# runpod-comfyui

Runpod Pod template for ComfyUI with fast startup, persistent volume storage, baked-in baseline custom nodes, and built-in `code-server`.

## What this image is for

- Start ComfyUI quickly on Runpod
- Keep models, outputs, workflows, and most custom nodes on a persistent volume
- Bake in a stable baseline so recovery is easy
- Support modern NVIDIA GPUs such as RTX 5090, H100, and RTX PRO 6000

## Recommended image variants

- `default-opt-enabled`
  Recommended default. Default baked node pack plus aggressive optimization extras (`triton`, `sageattention`).
- `default-opt-disabled`
  Same baked node pack, but without aggressive optimization extras.
- `image`
  Default pack plus image-focused nodes (`comfyui-portrait-master`, `ComfyUI-Sapiens2-Easy`, `comfyui_controlnet_aux`) with aggressive optimizations.
- `3d`
  Default pack plus 3D nodes (`ComfyUI-Sapiens2-Easy`, `ComfyUI-3D-Pack`) with aggressive optimizations.
- `video`
  Default pack plus video nodes (`ComfyUI-VideoHelperSuite`, `ComfyUI-WanVideoWrapper`, `ComfyUI-SeedVR2_VideoUpscaler`, `ComfyUI-FFmpeg`) with aggressive optimizations.

Image tags (example for release `v1.0.2`):

```text
ghcr.io/bogyie/runpod-comfyui:latest
ghcr.io/bogyie/runpod-comfyui:v1.0.2
ghcr.io/bogyie/runpod-comfyui:v1.0.2-default-opt-enabled
ghcr.io/bogyie/runpod-comfyui:py311-pt210-cu128-cf024-default-opt-enabled
ghcr.io/bogyie/runpod-comfyui:default-opt-enabled
```

Use a pinned release or version-slug tag for production templates rather than `latest`.

## Included in the image

- ComfyUI
- `ComfyUI-Manager`
- `code-server`
- Recovery scripts in `/opt/bootstrap/scripts`

Default baked custom node pack (every variant):

- `rgthree-comfy`
- `ComfyUI-KJNodes`
- `ComfyUI-Impact-Pack`
- `ComfyUI-Easy-Use`

Profile-specific nodes (added on top of the default pack):

- `image`: `comfyui-portrait-master`, `ComfyUI-Sapiens2-Easy`, `comfyui_controlnet_aux`
- `3d`: `ComfyUI-Sapiens2-Easy`, `ComfyUI-3D-Pack`
- `video`: `ComfyUI-VideoHelperSuite`, `ComfyUI-WanVideoWrapper`, `ComfyUI-SeedVR2_VideoUpscaler`, `ComfyUI-FFmpeg`

The baked repo lists live in `custom-nodes/*.txt`; edit those files to change which nodes are baked.

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

Model storage also follows the ComfyUI default `models/` layout, and common alias folders such as `unet`, `text_encoders`, and `t2i_adapter` are linked automatically to the matching storage paths.

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
