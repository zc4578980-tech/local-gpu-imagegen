#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from local_gpu_imagegen.backends.webui import WebUIAdapter
from local_gpu_imagegen.errors import AssetEngineError


DEFAULT_DIFFUSERS_MODEL = "stabilityai/sd-turbo"
DEFAULT_MODEL = os.environ.get("LOCAL_GPU_IMAGEGEN_MODEL")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path(os.environ.get("LOCAL_GPU_IMAGEGEN_OUTPUT_DIR", str(PROJECT_ROOT / "outputs")))
DEFAULT_WEBUI_URL = os.environ.get("LOCAL_GPU_IMAGEGEN_WEBUI_URL", "http://127.0.0.1:7860")


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return (slug[:limit].strip("-") or "image")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an image with a local CUDA GPU.")
    parser.add_argument("--prompt", required=True, help="Text prompt for the image.")
    parser.add_argument("--negative-prompt", default="", help="Optional negative prompt.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="WebUI checkpoint title or Hugging Face/local diffusers model.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated images.")
    parser.add_argument("--filename", help="Optional PNG filename.")
    parser.add_argument("--backend", choices=("auto", "webui", "diffusers"), default=os.environ.get("LOCAL_GPU_IMAGEGEN_BACKEND", "auto"))
    parser.add_argument("--mode", choices=("txt2img", "img2img", "inpaint"), default="txt2img")
    parser.add_argument("--webui-url", default=DEFAULT_WEBUI_URL, help="AUTOMATIC1111-compatible WebUI API URL.")
    parser.add_argument("--sampler-name", default=os.environ.get("LOCAL_GPU_IMAGEGEN_SAMPLER", "Euler a"))
    parser.add_argument("--scheduler", choices=("default", "dpmpp", "euler", "euler-a", "ddim", "unipc", "lcm"), default="default")
    parser.add_argument("--input-image", help="Source image for img2img or inpaint modes.")
    parser.add_argument("--mask-image", help="Mask image for inpaint mode. White areas are regenerated.")
    parser.add_argument("--strength", type=float, help="Denoising strength for img2img/inpaint. Typical range: 0.25-0.85.")
    parser.add_argument("--lora", action="append", default=[], help="Diffusers LoRA path or model id. May be passed more than once.")
    parser.add_argument("--lora-scale", type=float, default=1.0, help="Diffusers LoRA scale.")
    parser.add_argument("--cpu-offload", action="store_true", help="Enable Diffusers model CPU offload to reduce VRAM use.")
    parser.add_argument("--vae-tiling", action="store_true", help="Enable VAE tiling for large images.")
    parser.add_argument("--disable-safety-checker", action="store_true", help="Disable Diffusers safety checker when the pipeline supports it.")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--guidance-scale", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--allow-cpu", action="store_true", help="Allow CPU fallback if CUDA is unavailable.")
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow Diffusers to download model or LoRA files that are not already available locally.",
    )
    return parser.parse_args()


def validate_dimensions(width: int, height: int) -> None:
    if width < 256 or height < 256:
        raise ValueError("Width and height must be at least 256.")
    if width > 1536 or height > 1536:
        raise ValueError("Width and height must be 1536 or smaller for predictable local GPU use.")
    if width % 8 != 0 or height % 8 != 0:
        raise ValueError("Width and height must be divisible by 8.")


def validate_mode_args(args: argparse.Namespace) -> None:
    if args.mode in ("img2img", "inpaint") and not args.input_image:
        raise ValueError(f"--input-image is required for {args.mode} mode.")
    if args.mode == "inpaint" and not args.mask_image:
        raise ValueError("--mask-image is required for inpaint mode.")
    if args.strength is not None and not 0.0 <= args.strength <= 1.0:
        raise ValueError("--strength must be between 0 and 1.")
    if args.mode == "txt2img" and (args.input_image or args.mask_image):
        raise ValueError("--input-image and --mask-image are only valid for img2img/inpaint modes.")


def output_path_for(args: argparse.Namespace) -> Path:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = args.filename or f"{int(time.time())}-{slugify(args.prompt)}.png"
    filename = Path(filename).name
    if not filename.lower().endswith(".png"):
        filename += ".png"
    return output_dir / filename


def webui_available(base_url: str) -> bool:
    try:
        WebUIAdapter(base_url).probe()
    except (AssetEngineError, OSError, TimeoutError, ValueError):
        return False
    return True


def generate_with_webui(args: argparse.Namespace) -> dict[str, object]:
    adapter = WebUIAdapter(args.webui_url)
    models = adapter.discover()
    requested_model = args.model
    if requested_model is None:
        probe = adapter.probe()
        loaded_model = probe.get("loaded_model")
        requested_model = loaded_model if isinstance(loaded_model, str) else None
    selected = next(
        (
            model
            for model in models
            if model.get("backend_model_id") == requested_model
        ),
        None,
    )
    if selected is None:
        raise RuntimeError(
            f"WebUI model '{requested_model or 'current'}' is not available in the API inventory."
        )
    return adapter.generate({
        "backend": "webui",
        "model": selected,
        "mode": args.mode,
        "positive_prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "width": args.width,
        "height": args.height,
        "steps": args.steps if args.steps is not None else 20,
        "guidance_scale": args.guidance_scale if args.guidance_scale is not None else 7.0,
        "sampler": args.sampler_name,
        "seed": args.seed,
        "source_path": args.input_image,
        "mask_path": args.mask_image,
        "strength": (
            args.strength
            if args.strength is not None
            else 0.75 if args.mode in ("img2img", "inpaint") else None
        ),
        "output_path": str(output_path_for(args)),
        "prompt_compiler_id": "direct-v1",
        "prompt_compiler_version": 1,
    })


def apply_scheduler(pipeline: object, scheduler: str) -> None:
    if scheduler == "default":
        return

    import diffusers

    scheduler_map = {
        "dpmpp": "DPMSolverMultistepScheduler",
        "euler": "EulerDiscreteScheduler",
        "euler-a": "EulerAncestralDiscreteScheduler",
        "ddim": "DDIMScheduler",
        "unipc": "UniPCMultistepScheduler",
        "lcm": "LCMScheduler",
    }
    scheduler_class = getattr(diffusers, scheduler_map[scheduler])
    pipeline.scheduler = scheduler_class.from_config(pipeline.scheduler.config)


def load_condition_image(path: str, width: int, height: int) -> object:
    from PIL import Image

    return Image.open(path).convert("RGB").resize((width, height))


def hub_access_kwargs(allow_download: bool) -> dict[str, bool]:
    return {"local_files_only": not allow_download}


def generate_with_diffusers(args: argparse.Namespace) -> dict[str, object]:
    try:
        import torch
        from diffusers import AutoPipelineForImage2Image, AutoPipelineForInpainting, AutoPipelineForText2Image
    except ImportError as exc:
        raise RuntimeError(
            "Missing diffusers dependencies. Run scripts/install.ps1, use --backend webui, or start a local WebUI API."
        ) from exc

    cuda_available = torch.cuda.is_available()
    if not cuda_available and not args.allow_cpu:
        raise RuntimeError("CUDA is not available. This plugin will not use CPU unless --allow-cpu is set.")

    device = "cuda" if cuda_available else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = args.model or DEFAULT_DIFFUSERS_MODEL

    pipeline_class = AutoPipelineForText2Image
    if args.mode == "img2img":
        pipeline_class = AutoPipelineForImage2Image
    elif args.mode == "inpaint":
        pipeline_class = AutoPipelineForInpainting

    try:
        pipeline = pipeline_class.from_pretrained(
            model,
            torch_dtype=dtype,
            variant="fp16" if device == "cuda" else None,
            **hub_access_kwargs(args.allow_download),
        )
    except Exception as exc:
        if not args.allow_download:
            raise RuntimeError(
                f"Diffusers model '{model}' is not available locally. Preload it or explicitly pass --allow-download "
                "after reviewing its license and storage requirements."
            ) from exc
        raise RuntimeError(f"Failed to load Diffusers model '{model}': {exc}") from exc
    if args.disable_safety_checker and hasattr(pipeline, "safety_checker"):
        pipeline.safety_checker = None

    if args.cpu_offload and device == "cuda" and hasattr(pipeline, "enable_model_cpu_offload"):
        pipeline.enable_model_cpu_offload()
    else:
        pipeline = pipeline.to(device)

    apply_scheduler(pipeline, args.scheduler)

    if hasattr(pipeline, "enable_attention_slicing"):
        pipeline.enable_attention_slicing()
    if device == "cuda" and hasattr(pipeline, "enable_vae_slicing"):
        pipeline.enable_vae_slicing()
    if args.vae_tiling and hasattr(pipeline, "enable_vae_tiling"):
        pipeline.enable_vae_tiling()

    for lora in args.lora:
        try:
            pipeline.load_lora_weights(lora, **hub_access_kwargs(args.allow_download))
        except Exception as exc:
            raise RuntimeError(f"Failed to load LoRA '{lora}': {exc}") from exc
    if args.lora and hasattr(pipeline, "fuse_lora"):
        pipeline.fuse_lora(lora_scale=args.lora_scale)

    generator = None
    if args.seed is not None:
        generator = torch.Generator(device=device).manual_seed(args.seed)

    output_path = output_path_for(args)
    steps = args.steps if args.steps is not None else 4
    guidance_scale = args.guidance_scale if args.guidance_scale is not None else 0.0
    call_kwargs: dict[str, Any] = {
        "prompt": args.prompt,
        "width": args.width,
        "height": args.height,
        "num_inference_steps": steps,
        "guidance_scale": guidance_scale,
        "generator": generator,
    }
    if args.negative_prompt:
        call_kwargs["negative_prompt"] = args.negative_prompt
    if args.mode in ("img2img", "inpaint"):
        call_kwargs["image"] = load_condition_image(args.input_image, args.width, args.height)
        call_kwargs["strength"] = args.strength if args.strength is not None else 0.75
    if args.mode == "inpaint":
        call_kwargs["mask_image"] = load_condition_image(args.mask_image, args.width, args.height)

    image = pipeline(**call_kwargs).images[0]
    image.save(output_path)

    return {
        "ok": True,
        "path": str(output_path.resolve()),
        "backend": "diffusers",
        "mode": args.mode,
        "model": model,
        "device": device,
        "scheduler": args.scheduler,
        "width": args.width,
        "height": args.height,
        "steps": steps,
        "guidance_scale": guidance_scale,
        "strength": call_kwargs.get("strength"),
        "lora_count": len(args.lora),
        "seed": args.seed,
    }


def main() -> int:
    args = parse_args()
    validate_dimensions(args.width, args.height)
    validate_mode_args(args)

    if args.backend in ("auto", "webui") and webui_available(args.webui_url):
        try:
            result = generate_with_webui(args)
        except (AssetEngineError, OSError, TimeoutError, RuntimeError) as exc:
            raise SystemExit(f"WebUI generation failed: {exc}") from exc
    elif args.backend == "webui":
        raise SystemExit(f"WebUI API is not available at {args.webui_url}. Start WebUI with API enabled or use --backend diffusers.")
    else:
        try:
            result = generate_with_diffusers(args)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
