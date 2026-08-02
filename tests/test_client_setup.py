from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


class RecordingRunner:
    def __init__(
        self,
        *,
        get_returncode: int = 1,
        version: str = "test-client 1.0",
        version_returncode: int = 0,
        add_returncode: int = 0,
        stderr: str = "",
        get_stdout: str | None = None,
    ) -> None:
        self.get_returncode = get_returncode
        self.version = version
        self.version_returncode = version_returncode
        self.add_returncode = add_returncode
        self.stderr = stderr
        self.get_stdout = get_stdout
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
        encoding: str,
        errors: str,
    ) -> subprocess.CompletedProcess[str]:
        self.assert_subprocess_policy(
            capture_output,
            text,
            timeout,
            check,
            encoding,
            errors,
        )
        command = list(argv)
        self.calls.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(
                command,
                self.version_returncode,
                stdout=self.version + "\n",
                stderr=self.stderr,
            )
        if "get" in command:
            return subprocess.CompletedProcess(
                command,
                self.get_returncode,
                stdout=(
                    self.get_stdout
                    if self.get_stdout is not None
                    else "configured\n" if self.get_returncode == 0 else ""
                ),
                stderr=self.stderr,
            )
        if "add" in command:
            return subprocess.CompletedProcess(
                command,
                self.add_returncode,
                stdout="added\n" if self.add_returncode == 0 else "",
                stderr=self.stderr,
            )
        raise AssertionError(f"Unexpected command: {command}")

    @staticmethod
    def assert_subprocess_policy(
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
        encoding: str,
        errors: str,
    ) -> None:
        if (capture_output, text, timeout, check, encoding, errors) != (
            True,
            True,
            15,
            False,
            "utf-8",
            "replace",
        ):
            raise AssertionError("Setup subprocess policy changed.")


class ClientSetupTests(unittest.TestCase):
    def test_apply_rejects_an_existing_entry_with_a_different_launcher(self) -> None:
        from local_gpu_imagegen.client_setup import apply_setup_plan, build_setup_plan

        executables = {
            "claude": "C:/bin/claude.exe",
            "uvx": "C:/bin/uvx.exe",
        }
        plan = build_setup_plan(
            "claude-code",
            executable_lookup=executables.get,
            runner=RecordingRunner(
                get_returncode=0,
                get_stdout=(
                    "local-gpu-imagegen:\n"
                    "  Type: stdio\n"
                    "  Command: local-gpu-imagegen\n"
                    "  Args: serve\n"
                ),
            ),
        )

        self.assertEqual(plan["status"], "configuration_drift")
        self.assertFalse(plan["existing_matches"])
        with self.assertRaisesRegex(
            RuntimeError,
            "client_setup_drift:claude-code:remove_then_reapply",
        ):
            apply_setup_plan(plan, runner=RecordingRunner())

    def test_setup_plan_registers_a_resolved_version_pinned_uvx_launcher(self) -> None:
        from local_gpu_imagegen import __version__
        from local_gpu_imagegen.client_setup import build_setup_plan

        executables = {
            "claude": "C:/bin/claude.exe",
            "uvx": "C:/bin/uvx.exe",
        }
        plan = build_setup_plan(
            "claude-code",
            executable_lookup=executables.get,
            runner=RecordingRunner(get_returncode=1, version="2.1.220"),
        )

        server_command = [
            "C:/bin/uvx.exe",
            "--from",
            f"local-gpu-imagegen=={__version__}",
            "local-gpu-imagegen",
            "serve",
        ]
        self.assertEqual(plan["server"]["command"], server_command)
        self.assertEqual(plan["add_command"][-len(server_command) :], server_command)

    def test_static_contract_omits_executable_and_preserves_official_commands(self) -> None:
        from local_gpu_imagegen import __version__
        from local_gpu_imagegen.client_setup import setup_contract

        contract = setup_contract("claude-code")

        self.assertEqual(contract["binary"], "claude")
        self.assertEqual(
            contract["server"],
            {
                "name": "local-gpu-imagegen",
                "command": [
                    "uvx",
                    "--from",
                    f"local-gpu-imagegen=={__version__}",
                    "local-gpu-imagegen",
                    "serve",
                ],
            },
        )
        self.assertEqual(
            contract["add_args"],
            [
                "mcp",
                "add",
                "--scope",
                "user",
                "local-gpu-imagegen",
                "--",
                "uvx",
                "--from",
                f"local-gpu-imagegen=={__version__}",
                "local-gpu-imagegen",
                "serve",
            ],
        )
        self.assertNotIn("executable", contract)

    def test_codex_plan_is_read_only_and_exact(self) -> None:
        from local_gpu_imagegen import __version__
        from local_gpu_imagegen.client_setup import build_setup_plan

        runner = RecordingRunner(get_returncode=1, version="codex-cli 0.144.5")
        executables = {
            "codex": "C:/bin/codex.exe",
            "uvx": "C:/bin/uvx.exe",
        }
        plan = build_setup_plan(
            "codex",
            executable_lookup=executables.get,
            runner=runner,
        )

        self.assertFalse(plan["applied"])
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(
            plan["add_command"],
            [
                "C:/bin/codex.exe",
                "mcp",
                "add",
                "local-gpu-imagegen",
                "--",
                "C:/bin/uvx.exe",
                "--from",
                f"local-gpu-imagegen=={__version__}",
                "local-gpu-imagegen",
                "serve",
            ],
        )
        self.assertEqual(
            plan["remove_command"],
            [
                "C:/bin/codex.exe",
                "mcp",
                "remove",
                "local-gpu-imagegen",
            ],
        )
        self.assertNotIn(plan["add_command"], runner.calls)

    def test_claude_code_plan_uses_user_scope(self) -> None:
        from local_gpu_imagegen import __version__
        from local_gpu_imagegen.client_setup import build_setup_plan

        executables = {
            "claude": "C:/bin/claude.exe",
            "uvx": "C:/bin/uvx.exe",
        }
        plan = build_setup_plan(
            "claude-code",
            executable_lookup=executables.get,
            runner=RecordingRunner(get_returncode=1, version="2.1.195"),
        )

        self.assertEqual(
            plan["add_command"],
            [
                "C:/bin/claude.exe",
                "mcp",
                "add",
                "--scope",
                "user",
                "local-gpu-imagegen",
                "--",
                "C:/bin/uvx.exe",
                "--from",
                f"local-gpu-imagegen=={__version__}",
                "local-gpu-imagegen",
                "serve",
            ],
        )
        self.assertEqual(
            plan["remove_command"],
            [
                "C:/bin/claude.exe",
                "mcp",
                "remove",
                "--scope",
                "user",
                "local-gpu-imagegen",
            ],
        )

    def test_apply_is_idempotent_for_an_existing_entry(self) -> None:
        import json

        from local_gpu_imagegen import __version__
        from local_gpu_imagegen.client_setup import apply_setup_plan, build_setup_plan

        server_args = [
            "--from",
            f"local-gpu-imagegen=={__version__}",
            "local-gpu-imagegen",
            "serve",
        ]
        discovery_runner = RecordingRunner(
            get_returncode=0,
            get_stdout=json.dumps(
                {
                    "transport": {
                        "type": "stdio",
                        "command": "C:/bin/uvx.exe",
                        "args": server_args,
                    }
                }
            ),
        )
        executables = {
            "codex": "C:/bin/codex.exe",
            "uvx": "C:/bin/uvx.exe",
        }
        plan = build_setup_plan(
            "codex",
            executable_lookup=executables.get,
            runner=discovery_runner,
        )
        apply_runner = RecordingRunner()

        result = apply_setup_plan(plan, runner=apply_runner)

        self.assertEqual(result["status"], "already_configured")
        self.assertFalse(result["applied"])
        self.assertEqual(apply_runner.calls, [])

    def test_claude_existing_matching_launcher_is_idempotent(self) -> None:
        from local_gpu_imagegen import __version__
        from local_gpu_imagegen.client_setup import apply_setup_plan, build_setup_plan

        executable = "C:/Users/test/.local/bin/uvx.exe"
        args = (
            f"--from local-gpu-imagegen=={__version__} "
            "local-gpu-imagegen serve"
        )
        executables = {
            "claude": "C:/bin/claude.exe",
            "uvx": executable,
        }
        plan = build_setup_plan(
            "claude-code",
            executable_lookup=executables.get,
            runner=RecordingRunner(
                get_returncode=0,
                get_stdout=(
                    "local-gpu-imagegen:\n"
                    "  Type: stdio\n"
                    f"  Command: {executable}\n"
                    f"  Args: {args}\n"
                ),
            ),
        )
        apply_runner = RecordingRunner()

        result = apply_setup_plan(plan, runner=apply_runner)

        self.assertEqual(result["status"], "already_configured")
        self.assertTrue(result["existing_matches"])
        self.assertEqual(apply_runner.calls, [])

    def test_apply_invokes_only_the_planned_official_command(self) -> None:
        from local_gpu_imagegen.client_setup import apply_setup_plan, build_setup_plan

        plan = build_setup_plan(
            "codex",
            executable_lookup=lambda _binary: "codex",
            runner=RecordingRunner(get_returncode=1),
        )
        apply_runner = RecordingRunner(add_returncode=0)

        result = apply_setup_plan(plan, runner=apply_runner)

        self.assertTrue(result["applied"])
        self.assertEqual(result["status"], "configured")
        self.assertEqual(apply_runner.calls, [plan["add_command"]])

    def test_missing_unsupported_and_failed_clients_are_actionable(self) -> None:
        from local_gpu_imagegen.client_setup import build_setup_plan

        with self.assertRaisesRegex(ValueError, "unsupported_client:unknown"):
            build_setup_plan("unknown")
        with self.assertRaisesRegex(RuntimeError, "client_not_found:codex"):
            build_setup_plan("codex", executable_lookup=lambda _binary: None)
        with self.assertRaisesRegex(RuntimeError, "server_launcher_not_found:uvx"):
            build_setup_plan(
                "codex",
                executable_lookup=lambda binary: "codex" if binary == "codex" else None,
            )
        with self.assertRaisesRegex(RuntimeError, "client_version_failed:codex"):
            build_setup_plan(
                "codex",
                executable_lookup=lambda _binary: "codex",
                runner=RecordingRunner(version_returncode=2),
            )

    def test_apply_failure_truncates_client_stderr(self) -> None:
        from local_gpu_imagegen.client_setup import apply_setup_plan, build_setup_plan

        plan = build_setup_plan(
            "codex",
            executable_lookup=lambda _binary: "codex",
            runner=RecordingRunner(get_returncode=1),
        )

        with self.assertRaises(RuntimeError) as raised:
            apply_setup_plan(
                plan,
                runner=RecordingRunner(add_returncode=2, stderr="x" * 700),
            )

        message = str(raised.exception)
        self.assertTrue(message.startswith("client_setup_failed:codex:"))
        self.assertEqual(len(message.removeprefix("client_setup_failed:codex:")), 500)


if __name__ == "__main__":
    unittest.main()
