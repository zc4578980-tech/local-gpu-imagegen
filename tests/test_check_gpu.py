from __future__ import annotations

import io
import json
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
            patch.dict(sys.modules, {"torch": fake_torch}),
            redirect_stdout(output),
        ):
            exit_code = check_gpu.main()

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["webui_ready"])
        self.assertFalse(fake_cuda.called)


if __name__ == "__main__":
    unittest.main()
