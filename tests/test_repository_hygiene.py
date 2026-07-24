from __future__ import annotations

import json
import subprocess
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_hash_bound_workflows_disable_checkout_eol_conversion(self) -> None:
        attributes = ROOT / ".gitattributes"
        self.assertTrue(attributes.is_file())
        rules = attributes.read_text(encoding="utf-8").splitlines()
        self.assertIn("workflows/comfyui/*.json -text diff", rules)

    def test_mit_metadata_and_public_templates_are_retained(self) -> None:
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
        for path in (
            "SECURITY.md",
            "CONTRIBUTING.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
        ):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file(), path)

    def test_private_roots_are_ignored_and_untracked(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("outputs/", ignored)
        self.assertIn("docs/evidence/runs/", ignored)
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.replace("\\", "/").splitlines()
        self.assertFalse(
            any(path.startswith(("outputs/", "docs/evidence/runs/")) for path in tracked)
        )

    def test_tracked_public_files_do_not_contain_personal_absolute_roots(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        forbidden = (
            "C:" + "\\Users\\" + "Capricorn",
            "C:" + "\\\\Users\\\\" + "Capricorn",
            "D:" + "\\CodexWorkspace",
            "D:" + "\\AI\\envs\\" + "pytorch-vla",
        )
        findings: list[str] = []
        for relative in tracked:
            if relative.startswith("tests/"):
                continue
            path = ROOT / relative
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for value in forbidden:
                if value in content:
                    findings.append(f"{relative}:{value}")
        self.assertEqual(findings, [])

    def test_registry_metadata_is_exact_and_uses_uvx_stdio(self) -> None:
        server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertEqual(
            server["$schema"],
            "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        )
        self.assertEqual(server["name"], "io.github.zc4578980-tech/local-gpu-imagegen")
        self.assertEqual(server["version"], "0.8.0")
        self.assertLessEqual(len(server["description"]), 100)
        self.assertEqual(
            server["repository"],
            {
                "url": "https://github.com/zc4578980-tech/local-gpu-imagegen",
                "source": "github",
            },
        )
        self.assertEqual(len(server["packages"]), 1)
        self.assertEqual(
            server["packages"][0],
            {
                "registryType": "pypi",
                "registryBaseUrl": "https://pypi.org",
                "identifier": "local-gpu-imagegen",
                "version": "0.8.0",
                "runtimeHint": "uvx",
                "packageArguments": [
                    {"type": "positional", "value": "serve"},
                ],
                "transport": {"type": "stdio"},
            },
        )

    def test_registry_ownership_marker_and_prepared_directory_copy_are_explicit(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        listings = (ROOT / "docs" / "directory-listings.md").read_text(encoding="utf-8")
        self.assertIn(
            "mcp-name: io.github.zc4578980-tech/local-gpu-imagegen",
            readme,
        )
        self.assertIn("awesome-mcp-servers", listings)
        self.assertIn("Glama", listings)
        self.assertIn("Status: prepared, not submitted", listings)
        self.assertNotIn("Status: submitted", listings)


if __name__ == "__main__":
    unittest.main()
