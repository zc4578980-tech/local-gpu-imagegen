---
name: local-gpu-imagegen
description: Generate images from text prompts on the user's local CUDA GPU. Use when the user asks to create, draw, render, make, or generate an image locally, on this machine, or with the local GPU.
---

# Local GPU Imagegen

Use this skill when the user asks to generate or transform an image using the local machine's GPU.

## What This Plugin Provides

- An MCP tool named `local_gpu_generate_image`.
- A readiness tool named `local_gpu_imagegen_check`.
- A standalone Stable Diffusion script at `scripts/generate_image.py`.
- An installer helper at `scripts/install.ps1`.
- Automatic WebUI API support for an existing AUTOMATIC1111-compatible server.
- Text-to-image, image-to-image, and inpainting modes.
- Diffusers scheduler, LoRA, and memory optimization options.

Generated files default to:

```text
<plugin-root>\outputs
```

## Operating Rules

1. Prefer the MCP tool `local_gpu_generate_image` when it is available.
2. If MCP is not available, run `python scripts/generate_image.py` from the plugin root.
3. Before the first generation, use `local_gpu_imagegen_check` or `python scripts/check_gpu.py`.
4. When diagnosing MCP registration, run `python scripts/verify_mcp.py`; it requires no GPU or model.
5. If WebUI is running at `http://127.0.0.1:7860`, the plugin can generate through that API even when the current Python lacks diffusers dependencies.
6. If Python dependencies are missing and WebUI is not available, tell the user to run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

7. Do not download missing Diffusers models or LoRAs unless the user explicitly approves it. Downloads are disabled by default.
8. Do not silently fall back to CPU unless the user explicitly allows CPU generation. This plugin exists to use the local GPU.
9. Save generated images in the output folder and show the absolute path to the user.
10. Use `txt2img` for fresh images, `img2img` when the user provides a source image to restyle or vary, and `inpaint` when the user provides both source and mask images.

## Common Script Usage

```powershell
python .\scripts\generate_image.py `
  --prompt "a quiet futuristic train station at sunrise, painterly concept art" `
  --width 1024 `
  --height 1024
```

Image-to-image:

```powershell
python .\scripts\generate_image.py `
  --mode img2img `
  --input-image C:\path\to\source.png `
  --prompt "same composition, watercolor anime background" `
  --strength 0.55
```

Inpainting:

```powershell
python .\scripts\generate_image.py `
  --mode inpaint `
  --input-image C:\path\to\source.png `
  --mask-image C:\path\to\mask.png `
  --prompt "replace the masked object with a glowing lantern"
```

Useful options:

- `--backend`: `auto`, `webui`, or `diffusers`. Default is `auto`.
- `--mode`: `txt2img`, `img2img`, or `inpaint`.
- `--webui-url`: WebUI API URL. Default is `http://127.0.0.1:7860`.
- `--model`: WebUI checkpoint title or Hugging Face/local diffusers model path.
- `--negative-prompt`: Things to avoid.
- `--sampler-name`: WebUI sampler name.
- `--scheduler`: Diffusers scheduler: `default`, `dpmpp`, `euler`, `euler-a`, `ddim`, `unipc`, or `lcm`.
- `--input-image`: Source image for img2img/inpaint.
- `--mask-image`: Mask image for inpaint.
- `--strength`: Denoising strength for img2img/inpaint.
- `--lora`: Diffusers LoRA path/model id. Can be repeated.
- `--cpu-offload`: Reduce VRAM usage on CUDA.
- `--vae-tiling`: Use tiled VAE for large images.
- `--seed`: Fixed seed for reproducibility.
- `--output-dir`: Destination folder.
- `--allow-cpu`: Permit CPU fallback only when the user explicitly asks.
- `--allow-download`: Permit missing Diffusers model/LoRA downloads only after explicit user approval.

## Defaults

- Backend: `auto`, preferring a running local WebUI API.
- Diffusers model: `stabilityai/sd-turbo`
- Device: `cuda`, unless CPU is explicitly allowed.
- Model/LoRA network access: disabled unless `--allow-download` is set.
- Output directory: `<plugin-root>\outputs`, unless `LOCAL_GPU_IMAGEGEN_OUTPUT_DIR` is set.
- Width/height: `1024x1024`
- Steps: `20` for WebUI, `4` for diffusers SD Turbo, otherwise configurable.

## Stable Diffusion Reference Layer

This plugin incorporates the practical surface area commonly covered by Stable Diffusion skills:

- txt2img for direct prompt generation.
- img2img for source-image variation and style transfer.
- inpainting for masked edits.
- scheduler selection for Diffusers.
- LoRA loading for Diffusers workflows.
- attention slicing, VAE slicing/tiling, and CPU offload for lower VRAM use.

For WebUI, model, sampler, LoRA syntax, and extensions are delegated to the running AUTOMATIC1111-compatible server. For Diffusers, pass local paths or Hugging Face model ids directly.

## Installer Notes

`install.ps1` avoids Python 3.14/3.15 because PyTorch CUDA wheels are not reliably available there. It prefers Python 3.12 or 3.11, and can be overridden with:

```powershell
$env:LOCAL_GPU_IMAGEGEN_PYTHON = "C:\Path\To\python.exe"
```
