from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_acceptance_evidence import EvidenceError, validate_evidence  # noqa: E402
from tests.acceptance_evidence_helpers import (  # noqa: E402
    FIXTURE_PATH,
    build_complete_matrix,
    edit_json,
    write_json,
)


class AcceptanceEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_accepts_complete_real_matrix(self) -> None:
        root = build_complete_matrix(self.temp_path)
        result = validate_evidence(root, FIXTURE_PATH, strict=True)
        self.assertEqual(result["run_count"], 9)
        self.assertEqual(result["revision_count"], 3)
        self.assertEqual(result["profiles"], 3)
        self.assertTrue(result["release_ready"])
        self.assertTrue(result["ok"])

    def test_rejects_mock_marker(self) -> None:
        root = build_complete_matrix(self.temp_path)
        edit_json(root / "runs" / "ui-hero" / "evidence.json", ["backend", "implementation"], "fake-backend")
        with self.assertRaisesRegex(EvidenceError, "mock_evidence_forbidden"):
            validate_evidence(root, FIXTURE_PATH, strict=True)

    def test_rejects_route_that_does_not_match_acceptance_authority(self) -> None:
        root = build_complete_matrix(self.temp_path)
        edit_json(root / "runs" / "ui-hero" / "evidence.json", ["route", "sha256"], "0" * 64)
        with self.assertRaisesRegex(EvidenceError, "route_authority_mismatch"):
            validate_evidence(root, FIXTURE_PATH, strict=True)

    def test_rejects_private_endpoint_fields_in_exported_manifest(self) -> None:
        root = build_complete_matrix(self.temp_path)
        edit_json(
            root / "runs" / "ui-hero" / "manifest.json",
            ["request", "endpoint_identity"],
            "http://192.168.1.20:7860",
        )
        with self.assertRaisesRegex(EvidenceError, "private_evidence_value"):
            validate_evidence(root, FIXTURE_PATH, strict=True)

    def test_rejects_absolute_publishable_path(self) -> None:
        root = build_complete_matrix(self.temp_path)
        edit_json(root / "runs" / "ui-hero" / "evidence.json", ["files", "final"], r"D:\private\final.png")
        with self.assertRaisesRegex(EvidenceError, "absolute_evidence_path"):
            validate_evidence(root, FIXTURE_PATH, strict=True)

    def test_rejects_changed_parent_hash_in_revision(self) -> None:
        root = build_complete_matrix(self.temp_path)
        edit_json(root / "revisions" / "ui-hero" / "parent-evidence.json", ["image_sha256"], "0" * 64)
        with self.assertRaisesRegex(EvidenceError, "revision_parent_hash_mismatch"):
            validate_evidence(root, FIXTURE_PATH, strict=True)

    def test_rejects_unapproved_authority_as_active_authority(self) -> None:
        root = build_complete_matrix(self.temp_path)
        authority = json.loads((ROOT / "docs" / "evidence" / "acceptance-authority.example.json").read_text(encoding="utf-8"))
        write_json(root / "acceptance-authority.json", authority)
        with self.assertRaisesRegex(EvidenceError, "acceptance_authority_unapproved"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_non_strict_empty_repository_is_valid_but_not_release_ready(self) -> None:
        root = self.temp_path / "evidence"
        root.mkdir()
        result = validate_evidence(root, FIXTURE_PATH, strict=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_count"], 0)
        self.assertEqual(result["revision_count"], 0)
        self.assertFalse(result["release_ready"])

    def test_strict_requires_all_revision_evidence(self) -> None:
        root = build_complete_matrix(self.temp_path)
        revision = root / "revisions" / "ui-hero"
        for path in sorted(revision.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        revision.rmdir()
        with self.assertRaisesRegex(EvidenceError, "missing_revision_evidence"):
            validate_evidence(root, FIXTURE_PATH, strict=True)


if __name__ == "__main__":
    unittest.main()
