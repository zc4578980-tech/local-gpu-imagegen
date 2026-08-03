from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


class CliTests(unittest.TestCase):
    def test_help_lists_the_five_installed_commands(self) -> None:
        environment = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
        completed = subprocess.run(
            [sys.executable, "-m", "local_gpu_imagegen.cli", "--help"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )

        for command in ("serve", "doctor", "verify", "config", "setup"):
            self.assertIn(command, completed.stdout)

    def test_setup_dry_run_includes_readiness_without_apply(self) -> None:
        from local_gpu_imagegen import cli

        plan = {
            "client": "codex",
            "existing": False,
            "applied": False,
            "status": "planned",
        }
        output = io.StringIO()
        with (
            patch(
                "local_gpu_imagegen.client_setup.build_setup_plan",
                return_value=plan,
            ) as build,
            patch(
                "local_gpu_imagegen.client_setup.apply_setup_plan",
                side_effect=AssertionError("dry-run must not apply setup"),
            ) as apply,
            patch("check_gpu.collect_report", return_value={"ready": True}),
            redirect_stdout(output),
        ):
            exit_code = cli.main(["setup", "codex"])

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["backend_readiness"], {"ready": True})
        build.assert_called_once_with("codex")
        apply.assert_not_called()

    def test_setup_apply_uses_the_official_plan(self) -> None:
        from local_gpu_imagegen import cli

        plan = {"client": "claude-code", "existing": False, "applied": False}
        applied = {**plan, "applied": True, "status": "configured"}
        output = io.StringIO()
        with (
            patch(
                "local_gpu_imagegen.client_setup.build_setup_plan",
                return_value=plan,
            ),
            patch(
                "local_gpu_imagegen.client_setup.apply_setup_plan",
                return_value=applied,
            ) as apply,
            patch("check_gpu.collect_report", return_value={"ready": False}),
            redirect_stdout(output),
        ):
            exit_code = cli.main(["setup", "claude-code", "--apply"])

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["applied"])
        apply.assert_called_once_with(plan)

    def test_setup_error_is_machine_readable(self) -> None:
        from local_gpu_imagegen import cli

        error = io.StringIO()
        with (
            patch(
                "local_gpu_imagegen.client_setup.build_setup_plan",
                side_effect=RuntimeError("client_not_found:codex"),
            ),
            redirect_stderr(error),
        ):
            exit_code = cli.main(["setup", "codex"])

        report = json.loads(error.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["error"], "client_not_found:codex")

    def test_setup_managed_comfyui_passes_the_exact_server_command(self) -> None:
        from local_gpu_imagegen import cli

        command = ("uvx", "local-gpu-imagegen", "serve", "--auto-start-comfyui")
        plan = {"client": "codex", "existing": False, "applied": False}
        output = io.StringIO()
        with (
            patch(
                "local_gpu_imagegen.client_setup.managed_comfyui_server_command",
                return_value=command,
            ) as managed,
            patch(
                "local_gpu_imagegen.client_setup.build_setup_plan",
                return_value=plan,
            ) as build,
            patch("check_gpu.collect_report", return_value={"ready": False}),
            redirect_stdout(output),
        ):
            exit_code = cli.main(
                [
                    "setup",
                    "codex",
                    "--auto-start-comfyui",
                    "--comfyui-root",
                    "C:/portable",
                ]
            )

        self.assertEqual(exit_code, 0)
        managed.assert_called_once_with(
            "C:/portable",
            base_url="http://127.0.0.1:8188",
            timeout_seconds=120.0,
        )
        build.assert_called_once_with("codex", server_command=command)

    def test_setup_rejects_a_root_without_explicit_autostart(self) -> None:
        from local_gpu_imagegen import cli

        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = cli.main(["setup", "codex", "--comfyui-root", "C:/portable"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            json.loads(error.getvalue())["error"],
            "comfyui_options_require_autostart",
        )

    def test_managed_serve_starts_and_closes_one_supervisor(self) -> None:
        from local_gpu_imagegen import cli

        supervisor = unittest.mock.MagicMock()
        supervisor.close.return_value = {"cleanup_status": "stopped_owned_process"}
        config = object()
        with (
            patch(
                "local_gpu_imagegen.backend_lifecycle.build_comfyui_start_config",
                return_value=config,
            ) as build,
            patch(
                "local_gpu_imagegen.backend_lifecycle.ComfyUIProcessSupervisor",
                return_value=supervisor,
            ) as supervisor_class,
            patch("mcp_server.main", return_value=0) as serve,
        ):
            exit_code = cli.main(
                [
                    "serve",
                    "--auto-start-comfyui",
                    "--comfyui-root",
                    "C:/portable",
                ]
            )

        self.assertEqual(exit_code, 0)
        build.assert_called_once_with(
            "C:/portable",
            base_url="http://127.0.0.1:8188",
            timeout_seconds=120.0,
        )
        supervisor_class.assert_called_once_with(config)
        supervisor.start.assert_called_once_with()
        serve.assert_called_once_with()
        supervisor.close.assert_called_once_with()

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
        from local_gpu_imagegen import __version__
        from local_gpu_imagegen.cli import render_client_config

        rendered = render_client_config("codex")
        self.assertIn("[mcp_servers.local-gpu-imagegen]", rendered)
        self.assertIn('command = "uvx"', rendered)
        self.assertIn(
            f'args = ["--from", "local-gpu-imagegen=={__version__}", '
            '"local-gpu-imagegen", "serve"]',
            rendered,
        )
        self.assertNotIn(str(ROOT), rendered)

    def test_config_emits_claude_desktop_json_without_checkout_paths(self) -> None:
        from local_gpu_imagegen.client_setup import SERVER_COMMAND
        from local_gpu_imagegen.cli import render_client_config

        document = json.loads(render_client_config("claude-desktop"))
        server = document["mcpServers"]["local-gpu-imagegen"]
        self.assertEqual(
            server,
            {"command": SERVER_COMMAND[0], "args": list(SERVER_COMMAND[1:])},
        )
        self.assertNotIn(str(ROOT), json.dumps(document))


if __name__ == "__main__":
    unittest.main()
