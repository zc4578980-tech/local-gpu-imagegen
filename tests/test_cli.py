from __future__ import annotations

import json
import hashlib
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
    @staticmethod
    def _bootstrap_paths(root: Path):
        from local_gpu_imagegen.paths import BootstrapPaths

        return BootstrapPaths(root, root / "cache", root / "runtime", root / "plans")

    @staticmethod
    def _write_bootstrap_evidence(paths, transaction_status: str | None) -> None:
        from local_gpu_imagegen.bootstrap_catalog import BootstrapFacts, build_bootstrap_plan, load_bootstrap_manifest

        manifest = load_bootstrap_manifest(ROOT / "profiles" / "bootstrap" / "windows-nvidia.json")
        portable_root = paths.install / manifest.comfyui.install_relative_path
        python = portable_root / "python_embeded" / "python.exe"
        main = portable_root / "ComfyUI" / "main.py"
        model = paths.install / manifest.model.install_relative_path
        python.parent.mkdir(parents=True)
        main.parent.mkdir(parents=True)
        model.parent.mkdir(parents=True)
        python.write_bytes(b"synthetic-python")
        main.write_bytes(b"synthetic-main")
        with model.open("wb") as stream:
            stream.truncate(manifest.model.byte_size)
        if transaction_status is None:
            return
        facts = BootstrapFacts(
            "win32", "amd64", "nvidia", "rtx-50-series", 16 * 1024**3,
            26100, 40 * 1024**3, True, False, "missing", "missing",
        )
        plan = build_bootstrap_plan(
            manifest,
            facts,
            install_root=paths.install,
            plan_root=paths.plans,
        )
        transaction = {
            "schema_version": 1,
            "plan_id": plan.plan_id,
            "scope_sha256": plan.scope_sha256,
            "confirmation_sha256": hashlib.sha256(str(plan.confirmation).encode("utf-8")).hexdigest(),
            "status": transaction_status,
            "downloaded_artifacts": [manifest.comfyui.artifact_id, manifest.model.artifact_id],
            "failure_code": "bootstrap_execution_failed" if transaction_status == "failed" else None,
            "retained_state": {
                "portable": "installed",
                "model": "installed",
                "verified_cache_artifacts": [manifest.comfyui.artifact_id, manifest.model.artifact_id],
            },
            "recoverable_next_actions": ["create_new_plan_reusing_portable"] if transaction_status == "failed" else [],
        }
        (paths.plans / f"{plan.plan_id}.transaction.json").write_text(
            json.dumps(transaction), encoding="utf-8"
        )

    def test_help_lists_the_installed_commands_including_bootstrap(self) -> None:
        environment = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
        completed = subprocess.run(
            [sys.executable, "-m", "local_gpu_imagegen.cli", "--help"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )

        for command in ("serve", "doctor", "verify", "config", "setup", "bootstrap"):
            self.assertIn(command, completed.stdout)

    def test_bootstrap_status_is_json_only_and_does_not_create_state(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.paths import BootstrapPaths

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "bootstrap"
            paths = BootstrapPaths(
                root=root,
                cache=root / "cache",
                install=root / "runtime",
                plans=root / "plans",
            )
            output = io.StringIO()
            with (
                patch("local_gpu_imagegen.cli.default_bootstrap_paths", return_value=paths),
                redirect_stdout(output),
            ):
                exit_code = cli.main(["bootstrap", "status"])

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "not_installed")
        self.assertEqual(report["install_root"], str(paths.install))
        self.assertEqual(report["next_action"], "local-gpu-imagegen bootstrap plan --client codex")
        self.assertFalse(root.exists())

    def test_bootstrap_status_distinguishes_evidence_and_routes_next_actions(self) -> None:
        from local_gpu_imagegen import cli

        cases = (
            ("completed", "installed", "local-gpu-imagegen setup codex --apply"),
            ("failed", "recoverable", "local-gpu-imagegen bootstrap plan --client codex"),
            (None, "unknown", "local-gpu-imagegen bootstrap plan --client codex"),
        )
        for transaction_status, expected_status, expected_next_action in cases:
            with self.subTest(transaction_status=transaction_status), tempfile.TemporaryDirectory() as directory:
                paths = self._bootstrap_paths(Path(directory) / "bootstrap")
                self._write_bootstrap_evidence(paths, transaction_status)
                output = io.StringIO()
                with (
                    patch("local_gpu_imagegen.cli.default_bootstrap_paths", return_value=paths),
                    redirect_stdout(output),
                ):
                    exit_code = cli.main(["bootstrap", "status"])

            report = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["status"], expected_status)
            self.assertEqual(report["next_action"], expected_next_action)

    def test_bootstrap_plan_displays_effects_and_requires_later_confirmation(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.bootstrap_catalog import BootstrapFacts, BootstrapPlan
        from local_gpu_imagegen.paths import BootstrapPaths

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "bootstrap"
            paths = BootstrapPaths(
                root=root,
                cache=root / "cache",
                install=root / "runtime",
                plans=root / "plans",
            )
            plan = BootstrapPlan(
                plan_id="a" * 24,
                scope_sha256="b" * 64,
                confirmation=f"bootstrap:{'a' * 24}:{'b' * 64}",
                status="confirmation_required",
                reason=None,
                actions=(),
                required_download_bytes=12,
                required_disk_bytes=34,
                install_root=paths.install,
                record_path=paths.plans / ("a" * 24 + ".json"),
            )
            facts = BootstrapFacts(
                platform="win32",
                architecture="amd64",
                gpu_vendor="nvidia",
                gpu_generation="rtx-50-series",
                vram_bytes=16 * 1024**3,
                windows_build=26100,
                free_disk_bytes=40 * 1024**3,
                network_allowed=True,
                endpoint_ready=False,
                portable_status="missing",
                model_status="missing",
            )
            output = io.StringIO()
            with (
                patch("local_gpu_imagegen.cli.default_bootstrap_paths", return_value=paths),
                patch("local_gpu_imagegen.cli._collect_bootstrap_facts", return_value=facts),
                patch("local_gpu_imagegen.cli.build_bootstrap_plan", return_value=plan) as build,
                redirect_stdout(output),
            ):
                exit_code = cli.main(["bootstrap", "plan", "--client", "codex"])

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["plan_id"], plan.plan_id)
        self.assertEqual(report["confirmation"], plan.confirmation)
        self.assertEqual(report["estimated_download_bytes"], 12)
        self.assertEqual(report["estimated_disk_bytes"], 34)
        self.assertEqual(
            report["next_action"],
            f"local-gpu-imagegen bootstrap apply --plan-id {plan.plan_id} --confirmation {plan.confirmation}",
        )
        self.assertIn("licenses", report)
        self.assertNotIn("record_path", report)
        build.assert_called_once()

    def test_bootstrap_facts_measure_disk_from_an_existing_parent(self) -> None:
        from local_gpu_imagegen import cli

        readiness = {
            "cuda": {"available": False, "devices": []},
            "comfyui": {"available": False},
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_install_root = Path(temporary_directory) / "bootstrap" / "runtime"
            paths = self._bootstrap_paths(missing_install_root.parent)
            from local_gpu_imagegen.bootstrap_catalog import load_bootstrap_manifest

            manifest = load_bootstrap_manifest(ROOT / "profiles" / "bootstrap" / "windows-nvidia.json")
            with patch("check_gpu.collect_report", return_value=readiness):
                facts = cli._collect_bootstrap_facts(paths, manifest)

        self.assertGreater(facts.free_disk_bytes, 0)

    def test_bootstrap_facts_use_host_nvidia_when_plugin_torch_is_unavailable(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.bootstrap_catalog import load_bootstrap_manifest

        readiness = {
            "cuda": {"available": False, "devices": []},
            "host_gpu": {
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
            "comfyui": {"available": True},
        }
        manifest = load_bootstrap_manifest(ROOT / "profiles" / "bootstrap" / "windows-nvidia.json")
        with tempfile.TemporaryDirectory() as directory:
            paths = self._bootstrap_paths(Path(directory) / "bootstrap")
            with patch("check_gpu.collect_report", return_value=readiness):
                facts = cli._collect_bootstrap_facts(paths, manifest)

        self.assertEqual(facts.gpu_vendor, "nvidia")
        self.assertEqual(facts.gpu_generation, "rtx-50-series")
        self.assertEqual(facts.vram_bytes, 12227 * 1024**2)

    def test_bootstrap_facts_reuse_only_completed_verified_evidence(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.bootstrap_catalog import load_bootstrap_manifest

        readiness = {"cuda": {"available": False, "devices": []}, "comfyui": {"available": False}}
        manifest = load_bootstrap_manifest(ROOT / "profiles" / "bootstrap" / "windows-nvidia.json")
        cases = (("completed", ("valid", "valid")), (None, ("conflict", "conflict")))
        for transaction_status, expected in cases:
            with self.subTest(transaction_status=transaction_status), tempfile.TemporaryDirectory() as directory:
                paths = self._bootstrap_paths(Path(directory) / "bootstrap")
                self._write_bootstrap_evidence(paths, transaction_status)
                with patch("check_gpu.collect_report", return_value=readiness):
                    facts = cli._collect_bootstrap_facts(paths, manifest)

            self.assertEqual((facts.portable_status, facts.model_status), expected)

    def test_bootstrap_status_rejects_model_content_drift_without_reading_model_bytes(self) -> None:
        from local_gpu_imagegen import cli

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bootstrap_paths(Path(directory) / "bootstrap")
            self._write_bootstrap_evidence(paths, "completed")
            from local_gpu_imagegen.bootstrap_catalog import load_bootstrap_manifest

            manifest = load_bootstrap_manifest(ROOT / "profiles" / "bootstrap" / "windows-nvidia.json")
            model_path = paths.install / manifest.model.install_relative_path
            model_path.write_bytes(b"")
            output = io.StringIO()
            with (
                patch("local_gpu_imagegen.cli.default_bootstrap_paths", return_value=paths),
                redirect_stdout(output),
            ):
                exit_code = cli.main(["bootstrap", "status"])

            readiness = {"cuda": {"available": False, "devices": []}, "comfyui": {"available": False}}
            with patch("check_gpu.collect_report", return_value=readiness):
                facts = cli._collect_bootstrap_facts(paths, manifest)

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "recoverable")
        self.assertIn("completed_transaction_evidence_drift", report["reason_codes"])
        self.assertEqual((facts.portable_status, facts.model_status), ("conflict", "conflict"))

    def test_bootstrap_state_reader_rejects_plan_id_traversal_without_outside_read(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.bootstrap_catalog import load_bootstrap_manifest

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bootstrap_paths(Path(directory) / "bootstrap")
            paths.plans.mkdir(parents=True)
            manifest = load_bootstrap_manifest(ROOT / "profiles" / "bootstrap" / "windows-nvidia.json")
            transaction = {
                "schema_version": 1,
                "plan_id": "../outside",
                "scope_sha256": "a" * 64,
                "confirmation_sha256": "b" * 64,
                "status": "completed",
                "downloaded_artifacts": [],
                "failure_code": None,
                "retained_state": {
                    "portable": "installed",
                    "model": "installed",
                    "verified_cache_artifacts": [],
                },
                "recoverable_next_actions": [],
            }
            transaction_path = paths.plans / "record.transaction.json"
            transaction_path.write_text(json.dumps(transaction), encoding="utf-8")
            outside = paths.plans.parent / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            calls: list[Path] = []
            original_reader = cli._read_bootstrap_record

            def record_reader(path: Path):
                calls.append(path)
                return original_reader(path)

            with patch("local_gpu_imagegen.cli._read_bootstrap_record", side_effect=record_reader):
                self.assertIsNone(cli._matching_transaction_status(paths, manifest))

        self.assertFalse(any(path.resolve() == outside.resolve() for path in calls))

    def test_bootstrap_state_reader_rejects_replacement_between_lstat_and_open(self) -> None:
        from local_gpu_imagegen import cli

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            replacement = Path(directory) / "replacement.json"
            state.write_text('{"ok": true}', encoding="utf-8")
            replacement.write_text('{"ok": false}', encoding="utf-8")
            original_open = os.open

            def replace_before_open(path: str, *args, **kwargs):
                if Path(path) == state:
                    replacement.replace(state)
                return original_open(path, *args, **kwargs)

            with patch("local_gpu_imagegen.cli.os.open", new=replace_before_open):
                self.assertIsNone(cli._read_bootstrap_record(state))

    def test_bootstrap_state_reader_rejects_plans_root_replacement_before_scan(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.bootstrap_catalog import load_bootstrap_manifest
        from local_gpu_imagegen.paths import BootstrapPaths

        with tempfile.TemporaryDirectory() as directory:
            paths = self._bootstrap_paths(Path(directory) / "bootstrap")
            paths.plans.mkdir(parents=True)
            replacement = paths.root / "replacement-plans"
            replacement_paths = BootstrapPaths(paths.root, paths.cache, paths.install, replacement)
            self._write_bootstrap_evidence(replacement_paths, "completed")
            manifest = load_bootstrap_manifest(ROOT / "profiles" / "bootstrap" / "windows-nvidia.json")
            displaced = paths.root / "displaced-plans"
            original_scandir = os.scandir

            def replace_before_scan(path):
                if Path(path) == paths.plans:
                    paths.plans.replace(displaced)
                    replacement.replace(paths.plans)
                return original_scandir(path)

            with patch("local_gpu_imagegen.cli.os.scandir", new=replace_before_scan):
                self.assertIsNone(cli._matching_transaction_status(paths, manifest))

    def test_bootstrap_state_reader_rejects_symlink_state_file(self) -> None:
        from local_gpu_imagegen import cli

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            link = Path(directory) / "state.json"
            target.write_text('{"ok": true}', encoding="utf-8")
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            self.assertIsNone(cli._read_bootstrap_record(link))

    def test_bootstrap_apply_never_registers_a_client(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.paths import BootstrapPaths

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "bootstrap"
            paths = BootstrapPaths(root, root / "cache", root / "runtime", root / "plans")
            output = io.StringIO()
            with (
                patch("local_gpu_imagegen.cli.default_bootstrap_paths", return_value=paths),
                patch(
                    "local_gpu_imagegen.cli.apply_bootstrap_plan",
                    return_value={"ok": True, "status": "installed"},
                ) as apply,
                patch(
                    "local_gpu_imagegen.client_setup.apply_setup_plan",
                    side_effect=AssertionError("bootstrap must not register a client"),
                ),
                redirect_stdout(output),
            ):
                exit_code = cli.main(
                    [
                        "bootstrap",
                        "apply",
                        "--plan-id",
                        "a" * 24,
                        "--confirmation",
                        f"bootstrap:{'a' * 24}:{'b' * 64}",
                    ]
                )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["next_action"], "local-gpu-imagegen setup codex --apply")
        apply.assert_called_once_with(
            "a" * 24,
            f"bootstrap:{'a' * 24}:{'b' * 64}",
            state_dir=paths.plans,
        )

    def test_bootstrap_apply_retry_is_a_successful_idempotent_result(self) -> None:
        from local_gpu_imagegen import cli

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = self._bootstrap_paths(Path(temporary_directory) / "bootstrap")
            output = io.StringIO()
            with (
                patch("local_gpu_imagegen.cli.default_bootstrap_paths", return_value=paths),
                patch(
                    "local_gpu_imagegen.cli.apply_bootstrap_plan",
                    return_value={"ok": True, "status": "already_installed"},
                ),
                redirect_stdout(output),
            ):
                exit_code = cli.main(
                    [
                        "bootstrap", "apply", "--plan-id", "a" * 24,
                        "--confirmation", f"bootstrap:{'a' * 24}:{'b' * 64}",
                    ]
                )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "already_installed")
        self.assertEqual(report["next_action"], "local-gpu-imagegen setup codex --apply")

    def test_bootstrap_domain_errors_are_sanitized_json(self) -> None:
        from local_gpu_imagegen import cli
        from local_gpu_imagegen.bootstrap_catalog import BootstrapFacts
        from local_gpu_imagegen.errors import ValidationError
        from local_gpu_imagegen.paths import BootstrapPaths

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "bootstrap"
            paths = BootstrapPaths(root, root / "cache", root / "runtime", root / "plans")
            facts = BootstrapFacts(
                "win32", "amd64", "nvidia", "rtx-50-series", 16 * 1024**3,
                26100, 40 * 1024**3, True, False, "missing", "missing",
            )
            error = io.StringIO()
            with (
                patch("local_gpu_imagegen.cli.default_bootstrap_paths", return_value=paths),
                patch("local_gpu_imagegen.cli._collect_bootstrap_facts", return_value=facts),
                patch(
                    "local_gpu_imagegen.cli.build_bootstrap_plan",
                    side_effect=ValidationError("invalid_bootstrap_facts", "C:/private/token?secret=1"),
                ),
                redirect_stderr(error),
            ):
                exit_code = cli.main(["bootstrap", "plan", "--client", "codex"])

        report = json.loads(error.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(report, {"ok": False, "error": {"code": "invalid_bootstrap_facts"}})
        self.assertNotIn("private", error.getvalue())
        self.assertNotIn("secret", error.getvalue())

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
