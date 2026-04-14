# Build Reference

## Image model

### Variant dimensions

- `stable`
  Includes the recovery-friendly wheel cache in `/opt/wheels`.
- `slim`
  Removes the wheel cache to reduce runtime image size.
- `default-pack`
  Includes the full baked custom node pack.
- `manager-only`
  Bakes only `ComfyUI-Manager`.
- `safe`
  Conservative runtime.
- `aggressive`
  Adds experimental optimization packages.

### Published workflow variants

The GitHub Actions workflow currently publishes these explicit `stable` variants:

- `stable-default-aggr`
- `stable-default-safe`
- `stable-manager-aggr`
- `stable-manager-safe`

`stable-default-aggr` is treated as the canonical build and also receives short aliases like `latest`, `main`, and release tags.

## Build arguments

| Name | Default | Purpose |
|---|---|---|
| `COMFYUI_REF` | `v0.19.0` | ComfyUI git ref |
| `COMFYUI_MANAGER_REF` | `main` | ComfyUI-Manager git ref |
| `IMPACT_PACK_REF` | `Main` | Impact Pack git ref |
| `WAN_VIDEO_WRAPPER_REF` | `main` | WanVideoWrapper git ref |
| `CODE_SERVER_VERSION` | `4.103.2` | code-server version |
| `PYTHON_VERSION` | `3.11.15` | Exact CPython version compiled into the image |
| `XFORMERS_INSTALL_MODE` | `wheel` | Default xformers install path |
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

## Build-time guardrails

- A protected package manifest is captured after the base `torch/torchvision/torchaudio/xformers` install.
- After each baked custom node install step, the build verifies that critical packages have not drifted.
- The guarded package set includes `torch`, `torchvision`, `torchaudio`, `xformers`, `triton`, and `sageattention`.
- If a baked custom node tries to replace those packages unexpectedly, the Docker build fails.
- `aggressive` variants intentionally install `triton` and `sageattention`, then refresh the protected manifest after that step.

Custom node refs are resolved defensively during the build:

- Remote branches are checked out from `origin/<ref>` when they exist.
- Tags and commit SHAs are checked out directly.
- The build fails fast if a requested ref does not exist.

## GitHub Actions notes

- The workflow uses explicit matrix entries instead of a full cartesian matrix so additional variants can be added later without making tags noisy.
- PR smoke tests use a GPU-safe import check so builds can still validate on GitHub-hosted runners without NVIDIA drivers.

## Suggested next improvements

- Pin known-good git commits for ComfyUI and baked custom nodes.
- Add a healthcheck script for ports `8188` and `8080`.
- Add helper scripts for downloading models into the persistent volume.
- Add alternate compatibility or optimization image flavors after validation.
