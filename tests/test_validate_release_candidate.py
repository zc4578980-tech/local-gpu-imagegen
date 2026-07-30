from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_release_candidate as cli
import release_candidate_checks as checks


class StdoutCapture:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


class ValidateReleaseCandidateCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.wheel = self.root / "local_gpu_imagegen-0.8.0-py3-none-any.whl"
        self.wheel.write_bytes(b"wheel fixture")
        self.report = self.root / "report.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def passed_report() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "status": "passed",
            "candidate": {"version": "0.8.0"},
            "checks": [{"id": "fixture", "status": "passed", "observation": {}}],
            "next_action": "ready_for_separate_publication_authorization",
        }

    @staticmethod
    def blocked_report() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "candidate": None,
            "checks": [{"id": "fixture", "status": "blocked", "code": "fixture_blocked"}],
            "next_action": "fix_candidate_validation_and_rerun",
        }

    def run_main(
        self,
        report: dict[str, object] | None = None,
        *,
        report_path: Path | None = None,
        side_effect: BaseException | None = None,
        expected_commit: str = "a" * 40,
        expected_wheel_sha256: str = "b" * 64,
        python: str | None = None,
    ) -> tuple[int, bytes]:
        arguments = [
            "validate_release_candidate.py",
            "--wheel", str(self.wheel),
            "--expected-commit", expected_commit,
            "--expected-wheel-sha256", expected_wheel_sha256,
            "--python", python or sys.executable,
        ]
        if report_path is not None:
            arguments.extend(["--report", str(report_path)])
        capture = StdoutCapture()
        validator = patch.object(
            cli,
            "validate_candidate",
            return_value=report,
            side_effect=side_effect,
        )
        with validator, patch.object(sys, "argv", arguments), patch.object(sys, "stdout", capture):
            exit_code = cli.main()
        return exit_code, capture.buffer.getvalue()

    def test_cli_returns_zero_and_identical_stdout_and_report_for_pass(self) -> None:
        exit_code, stdout = self.run_main(self.passed_report(), report_path=self.report)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, self.report.read_bytes())

    def test_cli_returns_bounded_blocked_json_without_traceback(self) -> None:
        exit_code, stdout = self.run_main(
            side_effect=OSError("C:\\Users\\private\\secret")
        )
        self.assertEqual(exit_code, 1)
        report = json.loads(stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertNotIn(b"C:\\Users", stdout)
        self.assertNotIn(b"secret", stdout)
        self.assertNotIn(b"Traceback", stdout)

    def test_cli_preserves_existing_report_when_write_fails(self) -> None:
        self.report.write_bytes(b"original\n")
        exit_code, stdout = self.run_main(self.passed_report(), report_path=self.report)
        self.assertEqual(exit_code, 1)
        self.assertEqual(self.report.read_bytes(), b"original\n")
        self.assertEqual(json.loads(stdout)["status"], "blocked")

    def test_cli_stdout_matches_report_after_commit_then_raise(self) -> None:
        real_commit = checks._commit_report_install_if_absent

        def commit_then_raise(
            source_fd: int, parent_fd: int, destination: Path,
        ) -> None:
            real_commit(source_fd, parent_fd, destination)
            raise OSError("after commit")

        with patch.object(
            checks,
            "_commit_report_install_if_absent",
            side_effect=commit_then_raise,
        ):
            exit_code, stdout = self.run_main(
                self.passed_report(), report_path=self.report
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, self.report.read_bytes())

    def test_cli_removes_report_after_post_commit_parent_check_failure(self) -> None:
        with patch.object(
            checks,
            "_report_parent_is_bound",
            side_effect=(True, False),
        ):
            exit_code, stdout = self.run_main(
                self.passed_report(), report_path=self.report
            )

        self.assertEqual(exit_code, 1)
        self.assertFalse(self.report.exists())
        self.assertEqual(json.loads(stdout)["status"], "blocked")

    def test_cli_reports_bounded_cleanup_failure_code(self) -> None:
        with patch.object(
            cli,
            "atomic_write_report",
            side_effect=checks.ReportCleanupError("C:\\Users\\private"),
        ):
            exit_code, stdout = self.run_main(
                self.passed_report(), report_path=self.report
            )

        payload = json.loads(stdout)
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            payload["checks"],
            [
                {
                    "id": "runtime",
                    "status": "blocked",
                    "code": "candidate_report_cleanup_failed",
                }
            ],
        )
        self.assertNotIn(b"C:\\Users", stdout)

    def test_cli_keeps_validation_of_malformed_hashes_and_missing_python_in_validator(self) -> None:
        missing_python = self.root / "missing-python"
        arguments = [
            "validate_release_candidate.py",
            "--wheel", str(self.wheel),
            "--expected-commit", "invalid",
            "--expected-wheel-sha256", "invalid",
            "--python", str(missing_python),
        ]
        capture = StdoutCapture()
        with (
            patch.object(cli, "validate_candidate", return_value=self.blocked_report()) as validator,
            patch.object(sys, "argv", arguments),
            patch.object(sys, "stdout", capture),
        ):
            exit_code = cli.main()
        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(capture.buffer.getvalue())["status"], "blocked")
        self.assertEqual(validator.call_args.kwargs["expected_commit"], "invalid")
        self.assertEqual(validator.call_args.kwargs["expected_wheel_sha256"], "invalid")
        self.assertEqual(validator.call_args.kwargs["python"], missing_python)

    def test_unknown_arguments_remain_argparse_exit_two(self) -> None:
        arguments = [
            "validate_release_candidate.py",
            "--wheel", str(self.wheel),
            "--expected-commit", "a" * 40,
            "--expected-wheel-sha256", "b" * 64,
            "--python", sys.executable,
            "--unknown",
        ]
        with (
            patch.object(sys, "argv", arguments),
            self.assertRaises(SystemExit) as raised,
        ):
            cli.main()
        self.assertEqual(raised.exception.code, 2)
