from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


class VerifyMcpTests(unittest.TestCase):
    def test_readiness_request_is_optional(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import verify_mcp

        base_requests = verify_mcp.build_requests()
        readiness_requests = verify_mcp.build_requests(include_readiness=True)
        self.assertNotIn("local_gpu_imagegen_check", base_requests)
        self.assertIn("local_gpu_imagegen_check", readiness_requests)

    def test_verify_script_launches_server_and_checks_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "verify_mcp.py")],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )

        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["transport"], "stdio")
        self.assertEqual(report["server"]["name"], "local-gpu-imagegen")
        self.assertEqual(
            set(report["tools"]),
            {"local_gpu_imagegen_check", "local_gpu_generate_image"},
        )

    def test_missing_python_returns_json_error_without_traceback(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "verify_mcp.py"), "--python", "Z:\\missing\\python.exe"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        report = json.loads(completed.stderr)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(report["ok"])
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
