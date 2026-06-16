# runpod-comfyui

Runpod Pod template for ComfyUI with staged Docker images, persistent volume storage, purpose-built custom-node variants, and built-in recovery helpers.

## What this image is for

- Start ComfyUI quickly on Runpod
- Keep the PyTorch/CUDA/Python stack tied to one upstream PyTorch image tag
- Avoid rebuilding the full stack when only later layers change
- Keep models, outputs, workflows, and most mutable custom nodes on a persistent volume
- Publish separate final images for image and video workflows

## Staged image chain

The build starts from the upstream PyTorch image:

```text
pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel
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
| `runtime-tools` | Hugging Face CLI, git, curl, wget, runpodctl, GitHub CLI, and code-server |
| `custom-basic` | ComfyUI-Manager, KJNodes, rgthree-comfy, and Crystools |
| `custom-image` | controlnet aux, Impact Pack, and Sapiens2 Easy |
| `custom-video` | VideoHelperSuite |

Each Dockerfile ends with image cleanup and a low-cost smoke verification.

## Image tags

Image tags include stage tags, release tags, SHA tags, and a slug derived from the PyTorch base image tag plus ComfyUI version.

```text
ghcr.io/bogyie/runpod-comfyui:custom-image
ghcr.io/bogyie/runpod-comfyui:2-10-0-cuda12-8-cudnn9-devel-cf0240-custom-image
ghcr.io/bogyie/runpod-comfyui:v1.0.2-custom-image
ghcr.io/bogyie/runpod-comfyui:sha-abc1234-custom-image
```

On release, `custom-image` is also published as the bare release tag and `latest`. Use a pinned release, SHA, or version-slug tag for production templates rather than `latest`.

## Current baseline

- Base image: `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel`
- ComfyUI: `v0.24.0`
- Transformers: `5.12.0`
- xformers: `0.0.35`
- FlashAttention: `2.8.3`

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
