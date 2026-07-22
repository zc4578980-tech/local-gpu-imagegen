from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowTests(unittest.TestCase):
    def test_declared_build_backend_is_installed_before_suite(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        install = 'python -m pip install "setuptools>=68"'
        suite = "python -m unittest discover -s tests -v"

        self.assertIn(install, workflow)
        self.assertLess(workflow.index(install), workflow.index(suite))

    def test_public_matrix_keeps_four_required_jobs(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("os: [windows-latest, ubuntu-latest]", workflow)
        self.assertIn('python-version: ["3.11", "3.12"]', workflow)
        self.assertIn("fail-fast: false", workflow)


if __name__ == "__main__":
    unittest.main()
