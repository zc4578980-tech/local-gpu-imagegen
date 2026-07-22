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
    ) -> None:
        self.get_returncode = get_returncode
        self.version = version
        self.version_returncode = version_returncode
        self.add_returncode = add_returncode
        self.stderr = stderr
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
                stdout="configured\n" if self.get_returncode == 0 else "",
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
    def test_codex_plan_is_read_only_and_exact(self) -> None:
        from local_gpu_imagegen.client_setup import build_setup_plan

        runner = RecordingRunner(get_returncode=1, version="codex-cli 0.144.5")
        plan = build_setup_plan(
            "codex",
            executable_lookup=lambda _binary: "C:/bin/codex.exe",
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
        from local_gpu_imagegen.client_setup import build_setup_plan

        plan = build_setup_plan(
            "claude-code",
            executable_lookup=lambda _binary: "C:/bin/claude.exe",
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
        from local_gpu_imagegen.client_setup import apply_setup_plan, build_setup_plan

        discovery_runner = RecordingRunner(get_returncode=0)
        plan = build_setup_plan(
            "codex",
            executable_lookup=lambda _binary: "codex",
            runner=discovery_runner,
        )
        apply_runner = RecordingRunner()

        result = apply_setup_plan(plan, runner=apply_runner)

        self.assertEqual(result["status"], "already_configured")
        self.assertFalse(result["applied"])
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
