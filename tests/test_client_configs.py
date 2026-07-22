from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


class ClientConfigTests(unittest.TestCase):
    def test_named_setup_contracts_resolve_to_the_same_installed_command(self) -> None:
        from local_gpu_imagegen.client_setup import setup_contract

        codex = setup_contract("codex")
        claude = setup_contract("claude-code")
        self.assertEqual(codex["server"], claude["server"])
        self.assertEqual(
            codex["server"],
            {
                "name": "local-gpu-imagegen",
                "command": ["local-gpu-imagegen", "serve"],
            },
        )
        self.assertEqual(codex["add_args"][:3], ["mcp", "add", "local-gpu-imagegen"])
        self.assertEqual(claude["add_args"][:5], ["mcp", "add", "--scope", "user", "local-gpu-imagegen"])

    def test_claude_desktop_remains_a_legacy_render_only_template(self) -> None:
        from local_gpu_imagegen.cli import render_client_config

        claude = json.loads(render_client_config("claude-desktop"))["mcpServers"]["local-gpu-imagegen"]
        self.assertEqual(claude, {"command": "local-gpu-imagegen", "args": ["serve"]})

    def test_verifier_checks_both_contracts_and_exact_stdio_surface(self) -> None:
        import verify_client_configs

        report = verify_client_configs.verify_client_configs()
        self.assertTrue(report["ok"])
        self.assertEqual(report["verification_scope"], "configuration_contract_and_stdio_launch")
        self.assertFalse(report["hosted_client_session"])
        self.assertEqual(set(report["clients"]), {"codex", "claude-code"})
        self.assertEqual(set(report["legacy_templates"]), {"claude-desktop"})
        for client in report["clients"].values():
            self.assertTrue(client["config_valid"])
            self.assertEqual(client["configuration_kind"], "official_cli_setup_contract")
            self.assertEqual(client["server"]["name"], "local-gpu-imagegen")
            self.assertEqual(len(client["tools"]), 15)
        self.assertEqual(
            report["legacy_templates"]["claude-desktop"]["configuration_kind"],
            "render_only_template",
        )

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
