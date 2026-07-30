"""Validate one already-built Local GPU Imagegen release candidate wheel."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from release_candidate_checks import (
    atomic_write_report,
    blocked_runtime_report,
    canonical_report,
    validate_candidate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-wheel-sha256", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        report = validate_candidate(
            root=root,
            wheel=args.wheel,
            expected_commit=args.expected_commit,
            expected_wheel_sha256=args.expected_wheel_sha256,
            python=args.python,
        )
        encoded = canonical_report(report)
        if args.report is not None:
            atomic_write_report(args.report, encoded)
    except (OSError, ValueError, subprocess.SubprocessError):
        report = blocked_runtime_report("candidate_validation_failed")
        encoded = canonical_report(report)
    sys.stdout.buffer.write(encoded)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
