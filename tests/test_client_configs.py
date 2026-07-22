from __future__ import annotations

import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


class ClientConfigTests(unittest.TestCase):
    def test_named_configs_resolve_to_the_same_installed_command(self) -> None:
        from local_gpu_imagegen.cli import render_client_config

        codex = tomllib.loads(render_client_config("codex"))["mcp_servers"]["local-gpu-imagegen"]
        claude = json.loads(render_client_config("claude-desktop"))["mcpServers"]["local-gpu-imagegen"]
        self.assertEqual(codex, claude)
        self.assertEqual(codex, {"command": "local-gpu-imagegen", "args": ["serve"]})

    def test_verifier_checks_both_contracts_and_exact_stdio_surface(self) -> None:
        import verify_client_configs

        report = verify_client_configs.verify_client_configs()
        self.assertTrue(report["ok"])
        self.assertEqual(report["verification_scope"], "configuration_contract_and_stdio_launch")
        self.assertFalse(report["hosted_client_session"])
        self.assertEqual(set(report["clients"]), {"codex", "claude-desktop"})
        for client in report["clients"].values():
            self.assertTrue(client["config_valid"])
            self.assertEqual(client["server"]["name"], "local-gpu-imagegen")
            self.assertEqual(len(client["tools"]), 15)

    def test_verifier_script_returns_machine_readable_report(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "verify_client_configs.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertFalse(report["hosted_client_session"])

    def test_documentation_keeps_host_acceptance_pending(self) -> None:
        text = (ROOT / "docs" / "client-compatibility.md").read_text(encoding="utf-8")
        self.assertIn("Configuration contract", text)
        self.assertIn("not a real hosted LLM session", text)
        self.assertIn("Codex", text)
        self.assertIn("Claude Desktop", text)
        self.assertIn("Unverified client templates", text)


if __name__ == "__main__":
    unittest.main()
