from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_gpu  # noqa: E402


class FakeCuda:
    def __init__(self) -> None:
        self.called = False

    def is_available(self) -> bool:
        self.called = True
        return True

    def device_count(self) -> int:
        return 1

    def get_device_properties(self, _index: int) -> object:
        raise AssertionError("CUDA properties must not be read for a ready WebUI backend.")


class CheckGpuTests(unittest.TestCase):
    def test_collect_report_includes_host_nvidia_capability_when_comfyui_is_ready(self) -> None:
        output = io.StringIO()
        nvidia_smi = subprocess.CompletedProcess(
            args=["nvidia-smi"],
            returncode=0,
            stdout="NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12227, 610.62\n",
            stderr="",
        )
        with (
            patch.object(check_gpu, "module_available", return_value=False),
            patch.object(
                check_gpu,
                "check_webui",
                return_value={"url": "local-webui", "available": False, "model": None, "api_error": "stopped"},
            ),
            patch.object(
                check_gpu,
                "check_comfyui",
                return_value={"backend": "comfyui", "available": True, "api_error": None},
            ),
            patch("subprocess.run", return_value=nvidia_smi),
            redirect_stdout(output),
        ):
            report = check_gpu.collect_report()

        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            report.get("host_gpu"),
            {
                "available": True,
                "device_count": 1,
                "devices": [
                    {
                        "index": 0,
                        "name": "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
                        "total_memory_bytes": 12227 * 1024**2,
                        "driver_version": "610.62",
                    }
                ],
                "api_error": None,
            },
        )

    def test_collect_report_returns_readiness_without_printing(self) -> None:
        output = io.StringIO()
        with (
            patch.object(check_gpu, "module_available", return_value=False),
            patch.object(
                check_gpu,
                "check_webui",
                return_value={"url": "local-webui", "available": False, "model": None, "api_error": "stopped"},
            ),
            patch.object(
                check_gpu,
                "check_comfyui",
                return_value={"url": "local-comfyui", "available": True, "api_error": None},
            ),
            redirect_stdout(output),
        ):
            report = check_gpu.collect_report()

        self.assertEqual(output.getvalue(), "")
        self.assertTrue(report["ready"])
        self.assertTrue(report["comfyui_ready"])
        self.assertFalse(report["webui_ready"])

    def test_ready_webui_does_not_probe_optional_torch_runtime(self) -> None:
        fake_cuda = FakeCuda()
        fake_torch = ModuleType("torch")
        fake_torch.cuda = fake_cuda
        fake_torch.__version__ = "test"

        output = io.StringIO()
        with (
            patch.object(check_gpu, "module_available", return_value=True),
            patch.object(
                check_gpu,
                "check_webui",
                return_value={"url": "http://127.0.0.1:7860", "available": True, "model": "approved", "api_error": None},
            ),
            patch.object(
                check_gpu,
                "check_comfyui",
                return_value={"url": "http://127.0.0.1:8188", "available": False, "api_error": "backend_request_failed"},
            ),
            patch.dict(sys.modules, {"torch": fake_torch}),
            redirect_stdout(output),
        ):
            exit_code = check_gpu.main()

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["webui_ready"])
        self.assertFalse(fake_cuda.called)

    def test_ready_comfyui_does_not_probe_optional_torch_runtime(self) -> None:
        fake_cuda = FakeCuda()
        fake_torch = ModuleType("torch")
        fake_torch.cuda = fake_cuda
        fake_torch.__version__ = "test"

        output = io.StringIO()
        with (
            patch.object(check_gpu, "module_available", return_value=True),
            patch.object(
                check_gpu,
                "check_webui",
                return_value={"url": "http://127.0.0.1:7860", "available": False, "model": None, "api_error": "stopped"},
            ),
            patch.object(
                check_gpu,
                "check_comfyui",
                return_value={"backend": "comfyui", "available": True, "api_error": None},
            ),
            patch.dict(sys.modules, {"torch": fake_torch}),
            redirect_stdout(output),
        ):
            exit_code = check_gpu.main()

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["comfyui_ready"])
        self.assertFalse(report["webui_ready"])
        self.assertFalse(fake_cuda.called)

    def test_managed_start_is_reported_without_changing_readiness(self) -> None:
        adapter = unittest.mock.MagicMock()
        adapter.base_url = "http://127.0.0.1:8188"
        adapter.probe.return_value = {"backend": "comfyui", "ready": True}
        with (
            patch.object(check_gpu, "ComfyUIAdapter", return_value=adapter),
            patch.dict(
                check_gpu.os.environ,
                {
                    "LOCAL_GPU_IMAGEGEN_COMFYUI_MANAGED": "1",
                    "LOCAL_GPU_IMAGEGEN_COMFYUI_STARTUP_WAIT_SECONDS": "120",
                },
            ),
        ):
            report = check_gpu.check_comfyui()

        self.assertTrue(report["available"])
        self.assertTrue(report["managed_start"])

    def test_managed_check_waits_for_the_starting_backend(self) -> None:
        from local_gpu_imagegen.errors import AssetEngineError

        adapter = unittest.mock.MagicMock()
        adapter.base_url = "http://127.0.0.1:8188"
        adapter.probe.return_value = {"backend": "comfyui", "ready": True}
        with (
            patch.object(
                check_gpu,
                "ComfyUIAdapter",
                side_effect=(
                    AssetEngineError("backend_request_failed", "starting", "backend"),
                    adapter,
                ),
            ),
            patch.object(check_gpu.time, "monotonic", return_value=10.0),
            patch.object(check_gpu.time, "sleep") as sleep,
            patch.dict(
                check_gpu.os.environ,
                {"LOCAL_GPU_IMAGEGEN_COMFYUI_STARTUP_WAIT_SECONDS": "120"},
            ),
        ):
            report = check_gpu.check_comfyui()

        self.assertTrue(report["available"])
        sleep.assert_called_once_with(0.25)

    def test_managed_wait_caps_each_probe_to_the_remaining_budget(self) -> None:
        from local_gpu_imagegen.errors import AssetEngineError

        with (
            patch.object(
                check_gpu,
                "ComfyUIAdapter",
                side_effect=AssetEngineError(
                    "backend_request_failed",
                    "stopped",
                    "backend",
                ),
            ) as adapter,
            patch.object(
                check_gpu.time,
                "monotonic",
                side_effect=(10.0, 10.0, 11.0),
            ),
            patch.object(check_gpu.time, "sleep") as sleep,
            patch.dict(
                check_gpu.os.environ,
                {"LOCAL_GPU_IMAGEGEN_COMFYUI_STARTUP_WAIT_SECONDS": "1"},
            ),
        ):
            report = check_gpu.check_comfyui()

        self.assertFalse(report["available"])
        self.assertEqual(adapter.call_args.kwargs["timeout"], 1.0)
        sleep.assert_not_called()

    def test_nonfinite_managed_wait_fails_without_sleeping(self) -> None:
        from local_gpu_imagegen.errors import AssetEngineError

        with (
            patch.object(
                check_gpu,
                "ComfyUIAdapter",
                side_effect=AssetEngineError(
                    "backend_request_failed",
                    "stopped",
                    "backend",
                ),
            ),
            patch.object(check_gpu.time, "sleep") as sleep,
            patch.dict(
                check_gpu.os.environ,
                {"LOCAL_GPU_IMAGEGEN_COMFYUI_STARTUP_WAIT_SECONDS": "nan"},
            ),
        ):
            report = check_gpu.check_comfyui()

        self.assertFalse(report["available"])
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
