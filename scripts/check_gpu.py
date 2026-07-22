#!/usr/bin/env python
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request

from local_gpu_imagegen.backends.comfyui import ComfyUIAdapter
from local_gpu_imagegen.errors import AssetEngineError


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_webui() -> dict[str, object]:
    base_url = os.environ.get("LOCAL_GPU_IMAGEGEN_WEBUI_URL", "http://127.0.0.1:7860").rstrip("/")
    report: dict[str, object] = {
        "url": base_url,
        "available": False,
        "model": None,
        "api_error": None,
    }
    try:
        with urllib.request.urlopen(base_url + "/sdapi/v1/options", timeout=5) as response:
            options = json.loads(response.read().decode("utf-8"))
        report["available"] = True
        report["model"] = options.get("sd_model_checkpoint")
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        report["api_error"] = str(exc)
    return report


def check_comfyui() -> dict[str, object]:
    base_url = os.environ.get(
        "LOCAL_GPU_IMAGEGEN_COMFYUI_URL",
        "http://127.0.0.1:8188",
    )
    try:
        adapter = ComfyUIAdapter(base_url, timeout=5)
        return {
            **adapter.probe(),
            "url": adapter.base_url,
            "available": True,
            "api_error": None,
        }
    except AssetEngineError as error:
        return {
            "url": base_url,
            "available": False,
            "api_error": error.code,
        }


def collect_report() -> dict[str, object]:
    report: dict[str, object] = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "python_packages": {
            "torch": module_available("torch"),
            "diffusers": module_available("diffusers"),
            "transformers": module_available("transformers"),
            "PIL": module_available("PIL"),
        },
        "cuda": {
            "available": False,
            "device_count": 0,
            "devices": [],
        },
        "webui": check_webui(),
        "comfyui": check_comfyui(),
    }

    if (
        report["python_packages"]["torch"]
        and not report["webui"]["available"]
        and not report["comfyui"]["available"]
    ):
        import torch

        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
        devices = []
        for index in range(device_count):
            props = torch.cuda.get_device_properties(index)
            devices.append(
                {
                    "index": index,
                    "name": props.name,
                    "total_memory_gb": round(props.total_memory / (1024**3), 2),
                    "capability": f"{props.major}.{props.minor}",
                }
            )
        report["cuda"] = {
            "available": cuda_available,
            "device_count": device_count,
            "devices": devices,
            "torch_version": torch.__version__,
        }

    diffusers_ready = all(report["python_packages"].values()) and bool(report["cuda"]["available"])
    webui_ready = bool(report["webui"]["available"])
    comfyui_ready = bool(report["comfyui"]["available"])
    ready = diffusers_ready or webui_ready or comfyui_ready
    report["diffusers_ready"] = diffusers_ready
    report["webui_ready"] = webui_ready
    report["comfyui_ready"] = comfyui_ready
    report["ready"] = ready
    return report


def main() -> int:
    report = collect_report()
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
