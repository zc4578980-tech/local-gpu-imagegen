from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


class CliTests(unittest.TestCase):
    def test_help_lists_the_four_installed_commands(self) -> None:
        environment = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
        completed = subprocess.run(
            [sys.executable, "-m", "local_gpu_imagegen.cli", "--help"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )

        for command in ("serve", "doctor", "verify", "config"):
            self.assertIn(command, completed.stdout)

    def test_source_checkout_resource_root_is_detected(self) -> None:
        from local_gpu_imagegen.paths import resolve_resource_root

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOCAL_GPU_IMAGEGEN_ROOT", None)
            self.assertEqual(resolve_resource_root(), ROOT)

    def test_explicit_resource_root_must_contain_immutable_assets(self) -> None:
        from local_gpu_imagegen.paths import resolve_resource_root

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LOCAL_GPU_IMAGEGEN_ROOT": directory}):
                with self.assertRaisesRegex(RuntimeError, "profiles"):
                    resolve_resource_root()

    def test_config_emits_codex_toml_without_checkout_paths(self) -> None:
        from local_gpu_imagegen.cli import render_client_config

        rendered = render_client_config("codex")
        self.assertIn("[mcp_servers.local-gpu-imagegen]", rendered)
        self.assertIn('command = "local-gpu-imagegen"', rendered)
        self.assertIn('args = ["serve"]', rendered)
        self.assertNotIn(str(ROOT), rendered)

    def test_config_emits_claude_desktop_json_without_checkout_paths(self) -> None:
        from local_gpu_imagegen.cli import render_client_config

        document = json.loads(render_client_config("claude-desktop"))
        server = document["mcpServers"]["local-gpu-imagegen"]
        self.assertEqual(server, {"command": "local-gpu-imagegen", "args": ["serve"]})
        self.assertNotIn(str(ROOT), json.dumps(document))


if __name__ == "__main__":
    unittest.main()
