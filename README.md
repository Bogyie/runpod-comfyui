# runpod-comfyui

Runpod Pod template for ComfyUI with staged Docker images, persistent volume storage, a small baked custom-node baseline, and built-in recovery helpers.

## What this image is for

- Start ComfyUI quickly on Runpod
- Avoid rebuilding the full stack when only later layers change
- Keep models, outputs, workflows, and most custom nodes on a persistent volume
- Bake in a narrow custom-node baseline so recovery is predictable
- Support modern NVIDIA GPUs such as RTX 5090, H100, and RTX PRO 6000

## Staged image chain

The image is built as a linear chain. Each step uses the previous step image as `BASE_IMAGE`.

1. `core`
   ComfyUI, CUDA, Python, PyTorch, Transformers, and `ComfyUI-Manager`.
2. `runtime-tools`
   Adds operational tools such as `huggingface_hub[cli]`, `runpodctl`, `wget`, `jq`, SSH client, and `code-server`.
3. `optimized`
   Adds xformers and FlashAttention.
4. `custom-basic`
   Adds the basic custom node: `kijai/ComfyUI-KJNodes`.
5. `custom-advanced`
   Adds the advanced custom node: `Bogyie/ComfyUI-Sapiens2-Easy`.

The final recommended image is `custom-advanced`.

Image tags include stage tags and version-slug tags, for example:

```text
ghcr.io/bogyie/runpod-comfyui:custom-advanced
ghcr.io/bogyie/runpod-comfyui:py311-pt210-cu128-cf024-custom-advanced
ghcr.io/bogyie/runpod-comfyui:v1.0.2-custom-advanced
ghcr.io/bogyie/runpod-comfyui:v1.0.2
ghcr.io/bogyie/runpod-comfyui:latest
```

Use a pinned release or version-slug tag for production templates rather than `latest`.

## Current baseline stack

- ComfyUI `v0.24.0`
- CUDA `12.8`
- Python `3.11.15`
- PyTorch `2.10.0` with `cu128`
- torchvision `0.25.0`
- torchaudio `2.10.0`
- Transformers `5.12.0`
- xformers `0.0.35`
- FlashAttention `2.8.3`

## Included custom nodes

Core image:

- `ComfyUI-Manager`

Basic custom-node image:

- `ComfyUI-KJNodes`

Advanced custom-node image:

- `ComfyUI-Sapiens2-Easy`

Other custom nodes were intentionally removed from the baked baseline. Add them later only after validating their build-time and dependency impact.

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

Model storage follows the ComfyUI default `models/` layout, and common alias folders such as `unet`, `text_encoders`, and `t2i_adapter` are linked automatically to the matching storage paths.

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
