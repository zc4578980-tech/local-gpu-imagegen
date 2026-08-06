#!/usr/bin/env python
from __future__ import annotations

import importlib.util
import csv
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from local_gpu_imagegen.backends.comfyui import ComfyUIAdapter
from local_gpu_imagegen.errors import AssetEngineError


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_host_nvidia() -> dict[str, object]:
    report: dict[str, object] = {
        "available": False,
        "device_count": 0,
        "devices": [],
        "api_error": None,
    }
    try:
        completed = subprocess.run(
            (
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ),
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        report["api_error"] = "nvidia_smi_unavailable"
        return report
    if completed.returncode != 0:
        report["api_error"] = "nvidia_smi_failed"
        return report

    devices: list[dict[str, object]] = []
    try:
        rows = csv.reader(line for line in completed.stdout.splitlines() if line.strip())
        for index, row in enumerate(rows):
            if len(row) != 3:
                raise ValueError("invalid column count")
            name, memory_text, driver_version = (field.strip() for field in row)
            memory_mib = int(float(memory_text))
            if not name or memory_mib <= 0 or not driver_version:
                raise ValueError("invalid device metadata")
            devices.append(
                {
                    "index": index,
                    "name": name,
                    "total_memory_bytes": memory_mib * 1024**2,
                    "driver_version": driver_version,
                }
            )
    except (TypeError, ValueError):
        report["api_error"] = "nvidia_smi_invalid_output"
        return report
    if not devices:
        report["api_error"] = "nvidia_smi_no_devices"
        return report
    report["available"] = True
    report["device_count"] = len(devices)
    report["devices"] = devices
    return report


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
    wait_text = os.environ.get("LOCAL_GPU_IMAGEGEN_COMFYUI_STARTUP_WAIT_SECONDS", "0")
    try:
        parsed_wait = float(wait_text)
        wait_seconds = (
            min(max(parsed_wait, 0.0), 300.0)
            if math.isfinite(parsed_wait)
            else 0.0
        )
    except ValueError:
        wait_seconds = 0.0
    deadline = time.monotonic() + wait_seconds
    while True:
        attempt_timeout = 5.0
        if wait_seconds > 0:
            remaining = max(deadline - time.monotonic(), 0.0)
            attempt_timeout = max(min(5.0, remaining), 0.001)
        try:
            adapter = ComfyUIAdapter(base_url, timeout=attempt_timeout)
            return {
                **adapter.probe(),
                "url": adapter.base_url,
                "available": True,
                "managed_start": os.environ.get("LOCAL_GPU_IMAGEGEN_COMFYUI_MANAGED") == "1",
                "api_error": None,
            }
        except AssetEngineError as error:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {
                    "url": base_url,
                    "available": False,
                    "managed_start": os.environ.get("LOCAL_GPU_IMAGEGEN_COMFYUI_MANAGED") == "1",
                    "api_error": error.code,
                }
            time.sleep(min(0.25, remaining))


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
        "host_gpu": check_host_nvidia(),
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
