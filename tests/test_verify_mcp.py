from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

EXPECTED_TOOLS = {
    "local_gpu_imagegen_check",
    "local_gpu_generate_image",
    "local_gpu_list_profiles",
    "local_gpu_discover_models",
    "local_gpu_inspect_workflow",
    "local_gpu_register_workflow",
    "local_gpu_set_model_trust",
    "local_gpu_recommend_models",
    "local_gpu_start_run",
    "local_gpu_get_run",
    "local_gpu_branch_run",
    "local_gpu_prepare_mask",
    "local_gpu_confirm_mask",
    "local_gpu_generate_round",
    "local_gpu_record_review",
    "local_gpu_finalize_run",
    "local_gpu_cleanup_run",
}


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
        self.assertEqual(set(report["tools"]), EXPECTED_TOOLS)

    def test_verify_accepts_optional_exact_tool_contract(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import verify_mcp

        try:
            report = verify_mcp.verify(expected_tools=EXPECTED_TOOLS)
        except TypeError as exc:
            self.fail(f"verify must accept expected_tools: {exc}")
        self.assertEqual(set(report["tools"]), EXPECTED_TOOLS)

    def test_default_contract_is_exactly_seventeen_tools(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import verify_mcp

        self.assertEqual(verify_mcp.DEFAULT_EXPECTED_TOOLS, EXPECTED_TOOLS)
        self.assertEqual(set(verify_mcp.verify()["tools"]), EXPECTED_TOOLS)

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
