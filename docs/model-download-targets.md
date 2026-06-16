# Model Download Targets

Checked on 2026-06-16.

This document lists non-diffusion and non-LoRA model assets for ComfyUI model storage: CLIP or vision encoders, text encoders, model patches, VAEs, audio encoders, geometry estimation models, ControlNet files, and related checkpoints.

Source priority:

1. Use `Comfy-Org` repositories first.
2. If `Comfy-Org` does not provide the relevant helper asset, use the official repository when it exposes a matching file.
3. If neither exists in a ComfyUI-ready layout, note the nearest usable community source separately.

## Z Image / Z Image Turbo

Source: `Comfy-Org/z_image`

```text
models/text_encoders/zi(t)/qwen_3_4b.safetensors: https://huggingface.co/Comfy-Org/z_image/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors
models/text_encoders/zi(t)/qwen_3_4b_fp4_mixed.safetensors: https://huggingface.co/Comfy-Org/z_image/resolve/main/split_files/text_encoders/qwen_3_4b_fp4_mixed.safetensors
models/text_encoders/zi(t)/qwen_3_4b_fp8_mixed.safetensors: https://huggingface.co/Comfy-Org/z_image/resolve/main/split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors
models/vae/zi(t)/ae.safetensors: https://huggingface.co/Comfy-Org/z_image/resolve/main/split_files/vae/ae.safetensors
```

`Comfy-Org/z_image_turbo` provides the same helper assets under the same `split_files/text_encoders` and `split_files/vae` paths. Prefer `Comfy-Org/z_image` above to avoid duplicate downloads.

### Z Image Turbo ControlNet

Source: `alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1`

`Comfy-Org` does not currently provide these ControlNet files. The `alibaba-pai` repository is the upstream source. Use the 2.1 files unless a workflow explicitly asks for the older `Z-Image-Turbo-Fun-Controlnet-Union.safetensors` file.

```text
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Tile-2.1-2601-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Tile-2.1-2601-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Tile-2.1-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Tile-2.1-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Tile-2.1-lite-2601-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Tile-2.1-lite-2601-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union-2.0.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union-2.0.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union-2.1-2601-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union-2.1-2601-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union-2.1-2602-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union-2.1-2602-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union-2.1-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union-2.1-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2601-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2601-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union-2.1.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union-2.1.safetensors
```

Legacy source: `alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union`

```text
models/controlnet/z_image_turbo/Z-Image-Turbo-Fun-Controlnet-Union.safetensors: https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union/resolve/main/Z-Image-Turbo-Fun-Controlnet-Union.safetensors
```

## Z Image Edit

No separate `Comfy-Org` repository for `z image edit` was found. No official `Z-Image-Edit` repository with a clear ComfyUI-ready helper asset layout was confirmed. Reuse the Z Image / Z Image Turbo text encoder and VAE above only when a workflow explicitly expects the same Z Image helper assets.

## Wan 2.1

Source: `Comfy-Org/Wan_2.1_ComfyUI_repackaged`

```text
models/clip_vision/wan21/clip_vision_h.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors
models/model_patches/wan21/wan2.1_infiniteTalk_multi_fp16.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/model_patches/wan2.1_infiniteTalk_multi_fp16.safetensors
models/model_patches/wan21/wan2.1_infiniteTalk_single_fp16.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/model_patches/wan2.1_infiniteTalk_single_fp16.safetensors
models/text_encoders/wan21/umt5_xxl_fp16.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp16.safetensors
models/text_encoders/wan21/umt5_xxl_fp8_e4m3fn_scaled.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
models/vae/wan21/wan_2.1_vae.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors
models/vae/wan21/wan_alpha_2.1_vae_alpha_channel.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_alpha_2.1_vae_alpha_channel.safetensors
models/vae/wan21/wan_alpha_2.1_vae_rgb_channel.safetensors: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_alpha_2.1_vae_rgb_channel.safetensors
```

## SCAIL-2

Source: `Comfy-Org/SCAIL-2`

`Comfy-Org/SCAIL-2` provides Wan 2.1 14B SCAIL-2 diffusion model files and a DPO LoRA. It does not provide separate ComfyUI text encoder, CLIP vision, or VAE files. For ComfyUI workflows, use the Wan 2.1 helper assets listed in the previous section.

SCAIL-2 model files, included as a requested exception to the non-diffusion focus of this document:

```text
models/diffusion_models/scail2/wan2.1_14B_SCAIL_2_fp16.safetensors: https://huggingface.co/Comfy-Org/SCAIL-2/resolve/main/diffusion_models/wan2.1_14B_SCAIL_2_fp16.safetensors
models/diffusion_models/scail2/wan2.1_14B_SCAIL_2_fp8_scaled.safetensors: https://huggingface.co/Comfy-Org/SCAIL-2/resolve/main/diffusion_models/wan2.1_14B_SCAIL_2_fp8_scaled.safetensors
models/diffusion_models/scail2/wan2.1_14B_SCAIL_2_mxfp8.safetensors: https://huggingface.co/Comfy-Org/SCAIL-2/resolve/main/diffusion_models/wan2.1_14B_SCAIL_2_mxfp8.safetensors
```

Official repository for reference: `zai-org/SCAIL-2`

The official repository exposes helper assets as `.pth` files such as `Wan2.1_VAE.pth`, `models_clip_open-clip-xlm-roberta-large-vit-huge-14-onlyvisual.pth`, and `umt5-xxl/models_t5_umt5-xxl-enc-bf16.pth`. Prefer the ComfyUI-ready Wan 2.1 safetensors assets above unless a workflow specifically asks for the official `.pth` files.

## Wan 2.2

Source: `Comfy-Org/Wan_2.2_ComfyUI_Repackaged`

```text
models/audio_encoders/wan22/wav2vec2_large_english_fp16.safetensors: https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors
models/text_encoders/wan22/umt5_xxl_fp16.safetensors: https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp16.safetensors
models/text_encoders/wan22/umt5_xxl_fp8_e4m3fn_scaled.safetensors: https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors
models/vae/wan22/wan2.2_vae.safetensors: https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors
models/vae/wan22/wan_2.1_vae.safetensors: https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors
```

## Qwen Image / Qwen Image 2512 / Qwen Image Edit 2509 / 2511

Source: `Comfy-Org/Qwen-Image_ComfyUI`

`Comfy-Org/Qwen-Image_ComfyUI` contains Qwen Image 2512 diffusion model files and the shared helper assets. `Comfy-Org/Qwen-Image-Edit_ComfyUI` contains the 2509 and 2511 edit diffusion models and LoRAs, but no separate helper assets. Use the shared Qwen Image helper assets below for ComfyUI workflows that require the Qwen text encoder and VAE.

```text
models/text_encoders/qwen_image/qwen_2.5_vl_7b.safetensors: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b.safetensors
models/text_encoders/qwen_image/qwen_2.5_vl_7b_fp8_scaled.safetensors: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors
models/text_encoders/qwen_image/qwen_2.5_vl_7b_nvfp4.safetensors: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_nvfp4.safetensors
models/vae/qwen_image/qwen_image_vae.safetensors: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors
```

Qwen Image 2512 model files, included as a requested exception to the non-diffusion focus of this document:

```text
models/diffusion_models/qwen_image/qwen_image_2512_bf16.safetensors: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_2512_bf16.safetensors
models/diffusion_models/qwen_image/qwen_image_2512_fp8_e4m3fn.safetensors: https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors
```

### Qwen Image 2512 ControlNet

Source: `alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union`

`Comfy-Org` does not currently provide these ControlNet files. The `alibaba-pai` repository is the upstream source.

```text
models/controlnet/qwen_image_2512/Qwen-Image-2512-Fun-Controlnet-Union-2602.safetensors: https://huggingface.co/alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union/resolve/main/Qwen-Image-2512-Fun-Controlnet-Union-2602.safetensors
models/controlnet/qwen_image_2512/Qwen-Image-2512-Fun-Controlnet-Union.safetensors: https://huggingface.co/alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union/resolve/main/Qwen-Image-2512-Fun-Controlnet-Union.safetensors
```

Official Diffusers repositories for reference:

- `Qwen/Qwen-Image-Edit-2509`
- `Qwen/Qwen-Image-Edit-2511`

These official repositories expose Diffusers component folders such as `text_encoder/`, `tokenizer/`, `processor/`, `scheduler/`, `transformer/`, and `vae/`, not the ComfyUI single-file helper layout above.

## Ideogram 4

Source: `Comfy-Org/Ideogram-4`

```text
models/text_encoders/ideogram4/qwen3vl_8b_fp8_scaled.safetensors: https://huggingface.co/Comfy-Org/Ideogram-4/resolve/main/text_encoders/qwen3vl_8b_fp8_scaled.safetensors
models/text_encoders/ideogram4/qwen3vl_8b_nvfp4.safetensors: https://huggingface.co/Comfy-Org/Ideogram-4/resolve/main/text_encoders/qwen3vl_8b_nvfp4.safetensors
models/vae/ideogram4/flux2-vae.safetensors: https://huggingface.co/Comfy-Org/Ideogram-4/resolve/main/vae/flux2-vae.safetensors
```

## Depth Anything 3

Source: `Comfy-Org/Depth-Anything-3`

```text
models/geometry_estimation/depth_anything3/depth_anything_3_base.safetensors: https://huggingface.co/Comfy-Org/Depth-Anything-3/resolve/main/geometry_estimation/depth_anything_3_base.safetensors
models/geometry_estimation/depth_anything3/depth_anything_3_metric_large.safetensors: https://huggingface.co/Comfy-Org/Depth-Anything-3/resolve/main/geometry_estimation/depth_anything_3_metric_large.safetensors
models/geometry_estimation/depth_anything3/depth_anything_3_mono_large.safetensors: https://huggingface.co/Comfy-Org/Depth-Anything-3/resolve/main/geometry_estimation/depth_anything_3_mono_large.safetensors
models/geometry_estimation/depth_anything3/depth_anything_3_small.safetensors: https://huggingface.co/Comfy-Org/Depth-Anything-3/resolve/main/geometry_estimation/depth_anything_3_small.safetensors
```

## SeedVR2

Source: `Comfy-Org/SeedVR2`

```text
models/vae/seedvr2/ema_vae_fp16.safetensors: https://huggingface.co/Comfy-Org/SeedVR2/resolve/main/vae/ema_vae_fp16.safetensors
```

## SAM 3.1

Source: `Comfy-Org/sam3.1`

```text
models/checkpoints/sam31/sam3.1_multiplex_fp16.safetensors: https://huggingface.co/Comfy-Org/sam3.1/resolve/main/checkpoints/sam3.1_multiplex_fp16.safetensors
```

## FLUX.2 Dev

Source: `Comfy-Org/flux2-dev`

```text
models/text_encoders/flux2_dev/mistral_3_small_flux2_bf16.safetensors: https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/text_encoders/mistral_3_small_flux2_bf16.safetensors
models/text_encoders/flux2_dev/mistral_3_small_flux2_fp4_mixed.safetensors: https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/text_encoders/mistral_3_small_flux2_fp4_mixed.safetensors
models/text_encoders/flux2_dev/mistral_3_small_flux2_fp8.safetensors: https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/text_encoders/mistral_3_small_flux2_fp8.safetensors
models/vae/flux2_dev/flux2-vae.safetensors: https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors
```

## FLUX.2 Klein 4B

Source: `Comfy-Org/vae-text-encorder-for-flux-klein-4b`

```text
models/text_encoders/flux2_klein_4b/qwen_3_4b.safetensors: https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors
models/text_encoders/flux2_klein_4b/qwen_3_4b_fp4_flux2.safetensors: https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b/resolve/main/split_files/text_encoders/qwen_3_4b_fp4_flux2.safetensors
models/vae/flux2_klein_4b/flux2-vae.safetensors: https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b/resolve/main/split_files/vae/flux2-vae.safetensors
```

## FLUX.2 Klein 9B

Source: `Comfy-Org/vae-text-encorder-for-flux-klein-9b`

```text
models/text_encoders/flux2_klein_9b/qwen_3_8b.safetensors: https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/resolve/main/split_files/text_encoders/qwen_3_8b.safetensors
models/text_encoders/flux2_klein_9b/qwen_3_8b_fp4mixed.safetensors: https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/resolve/main/split_files/text_encoders/qwen_3_8b_fp4mixed.safetensors
models/text_encoders/flux2_klein_9b/qwen_3_8b_fp8mixed.safetensors: https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors
models/vae/flux2_klein_9b/flux2-vae.safetensors: https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/resolve/main/split_files/vae/flux2-vae.safetensors
```

## LTX 2

Source: `Comfy-Org/ltx-2`

```text
models/text_encoders/ltx2/gemma_3_12B_it.safetensors: https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it.safetensors
models/text_encoders/ltx2/gemma_3_12B_it_fp4_mixed.safetensors: https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors
models/text_encoders/ltx2/gemma_3_12B_it_fp8_scaled.safetensors: https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors
models/text_encoders/ltx2/gemma_3_12B_it_fpmixed.safetensors: https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fpmixed.safetensors
```

## LTX 2.3

`Comfy-Org/ltx-2.3` currently contains LoRA files only. The official `Lightricks/LTX-2.3` repository contains full model, distilled model, LoRA, and upscaler safetensors, but no separate ComfyUI helper text encoder or VAE files.

Nearest ComfyUI-ready community source: `Kijai/LTX2.3_comfy`

```text
models/text_encoders/ltx23/ltx-2.3_text_projection_bf16.safetensors: https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/text_encoders/ltx-2.3_text_projection_bf16.safetensors
models/vae/ltx23/LTX23_audio_vae_bf16.safetensors: https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/LTX23_audio_vae_bf16.safetensors
models/vae/ltx23/LTX23_video_vae_bf16.safetensors: https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/LTX23_video_vae_bf16.safetensors
models/vae/ltx23/taeltx2_3.safetensors: https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/taeltx2_3.safetensors
```