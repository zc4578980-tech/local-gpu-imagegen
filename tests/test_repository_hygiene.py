from __future__ import annotations

import hashlib
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

    def test_social_preview_html_uses_portable_hash_bound_line_endings(self) -> None:
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn("docs/assets/github-social-preview.html text eol=lf", rules)

    def test_hash_bound_public_evidence_uses_portable_lf_checkout(self) -> None:
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn("docs/demo/real/*.json text eol=lf", rules)
        self.assertIn("docs/demo/real/*.md text eol=lf", rules)
        self.assertIn("docs/evidence/client-sessions/*.json text eol=lf", rules)

    def test_acceptance_briefs_are_bound_to_committed_bytes(self) -> None:
        relative = "tests/fixtures/acceptance/v1-briefs.json"
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn(f"{relative} -text diff", rules)

        committed = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{relative}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        authority = json.loads(
            (ROOT / "docs" / "evidence" / "acceptance-authority.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            authority["briefs_sha256"],
            hashlib.sha256(committed).hexdigest(),
        )

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
        self.assertIn("local-gpu-imagegen==0.8.0", listings)
        self.assertIn("Status: prepared, not submitted", listings)
        self.assertIn(
            "No current-v0.8 hosted-client generation release set is retained.",
            listings,
        )
        self.assertIn("Complete 9+3 acceptance is not claimed.", listings)
        self.assertNotIn("local-gpu-imagegen==0.7.0", listings)
        self.assertNotIn("Status: submitted", listings)


if __name__ == "__main__":
    unittest.main()
