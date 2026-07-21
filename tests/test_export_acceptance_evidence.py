from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_acceptance_evidence import EvidenceExportError, export_run  # noqa: E402
from tests.acceptance_evidence_helpers import (  # noqa: E402
    FIXTURE_PATH,
    approved_authority,
    build_run_source,
    observed_metadata,
    read_json,
    sha256_file,
    write_json,
)


class ExportAcceptanceEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.briefs = read_json(FIXTURE_PATH)
        self.brief = next(item for item in self.briefs if item["id"] == "ui-section")
        self.run_dir = build_run_source(self.temp_path / "runs", self.brief)
        self.evidence_root = self.temp_path / "evidence"
        write_json(self.evidence_root / "acceptance-authority.json", approved_authority())
        self.destination = self.evidence_root / "runs" / self.brief["id"]
        self.metadata_path = self.temp_path / "metadata.json"
        write_json(self.metadata_path, observed_metadata(str(self.brief["id"])))
        self.run_id = str(read_json(self.run_dir / "manifest.json")["run_id"])

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def export(self) -> dict[str, object]:
        return export_run(
            self.run_dir,
            self.destination,
            FIXTURE_PATH,
            self.metadata_path,
            self.run_id,
            None,
        )

    def test_exports_finalized_run_without_changing_artifact_bytes(self) -> None:
        source_hash = sha256_file(self.run_dir / "round-01.png")
        result = self.export()
        self.assertTrue(result["ok"])
        self.assertEqual(source_hash, sha256_file(self.destination / "round-01.png"))
        self.assertEqual(source_hash, sha256_file(self.destination / "final.png"))
        manifest = read_json(self.destination / "manifest.json")
        self.assertEqual(manifest["rounds"][0]["image"]["path"], "round-01.png")
        self.assertFalse(any(Path(value).is_absolute() for value in _path_values(manifest)))
        self.assertFalse((self.destination / "unrelated.tmp").exists())
        self.assertEqual(read_json(self.destination / "mcp-final-result.json")["run_id"], self.run_id)

    def test_rejects_existing_destination(self) -> None:
        self.destination.mkdir(parents=True)
        with self.assertRaisesRegex(EvidenceExportError, "evidence_destination_exists"):
            self.export()

    def test_rejects_non_finalized_run(self) -> None:
        manifest = read_json(self.run_dir / "manifest.json")
        manifest["state"] = "reviewed"
        write_json(self.run_dir / "manifest.json", manifest)
        with self.assertRaisesRegex(EvidenceExportError, "run_not_finalized"):
            self.export()

    def test_rejects_missing_preview_without_warning(self) -> None:
        manifest = read_json(self.run_dir / "manifest.json")
        manifest["rounds"][0]["preview"] = None
        write_json(self.run_dir / "manifest.json", manifest)
        with self.assertRaisesRegex(EvidenceExportError, "preview_evidence_missing"):
            self.export()

    def test_rejects_artifact_hash_mismatch(self) -> None:
        (self.run_dir / "round-01.png").write_bytes(b"changed")
        with self.assertRaisesRegex(EvidenceExportError, "artifact_hash_mismatch"):
            self.export()

    def test_rejects_mock_backend_marker(self) -> None:
        manifest = read_json(self.run_dir / "manifest.json")
        manifest["rounds"][0]["backend_result"]["backend"] = "fake-backend"
        write_json(self.run_dir / "manifest.json", manifest)
        with self.assertRaisesRegex(EvidenceExportError, "mock_evidence_forbidden"):
            self.export()

    def test_private_or_backend_binding_route_cannot_enter_public_evidence(self) -> None:
        routes = (
            {**_public_route(), "authorization_scope": "private"},
            {**_public_route(), "identity_strength": "backend_binding", "sha256": None},
        )
        for index, route in enumerate(routes):
            manifest = read_json(self.run_dir / "manifest.json")
            manifest["request"]["route"] = route
            write_json(self.run_dir / "manifest.json", manifest)
            with self.subTest(route=route), self.assertRaisesRegex(
                EvidenceExportError,
                "public_model_evidence_forbidden",
            ):
                export_run(
                    self.run_dir,
                    self.evidence_root / "runs" / f"{self.brief['id']}-{index}",
                    FIXTURE_PATH,
                    self.metadata_path,
                    self.run_id,
                    None,
                )

    def test_export_redacts_private_route_and_backend_binding_values(self) -> None:
        manifest = read_json(self.run_dir / "manifest.json")
        manifest["request"]["route"] = _public_route()
        manifest["request"]["model_record"] = {
            "id": "approved-local-model",
            "backend_model_id": "private-checkpoint-name.safetensors",
            "endpoint_identity": "endpoint:private",
            "local_path": r"D:\private\model.safetensors",
        }
        manifest["rounds"][0]["backend_result"].update({
            "endpoint_identity": "endpoint:private",
            "webui_url": "http://192.168.1.20:7860",
            "model": "private-checkpoint-name.safetensors",
        })
        write_json(self.run_dir / "manifest.json", manifest)

        self.export()

        exported = read_json(self.destination / "manifest.json")
        serialized = json.dumps(exported, sort_keys=True)
        self.assertNotIn("endpoint_identity", serialized)
        self.assertNotIn("backend_model_id", serialized)
        self.assertNotIn("private-checkpoint-name", serialized)
        self.assertNotIn("192.168.1.20", serialized)
        evidence = read_json(self.destination / "evidence.json")
        self.assertEqual(evidence["route"]["model_id"], "approved-local-model")
        self.assertEqual(evidence["route"]["sha256"], "a" * 64)

    def test_requires_exact_run_id_confirmation(self) -> None:
        with self.assertRaisesRegex(EvidenceExportError, "real_run_confirmation_mismatch"):
            export_run(
                self.run_dir,
                self.destination,
                FIXTURE_PATH,
                self.metadata_path,
                "a-different-run",
                None,
            )

    def test_rejects_mcp_result_that_does_not_match_manifest(self) -> None:
        result = read_json(self.run_dir / "mcp-final-result.json")
        result["run_id"] = "reconstructed-run"
        write_json(self.run_dir / "mcp-final-result.json", result)
        with self.assertRaisesRegex(EvidenceExportError, "mcp_result_mismatch"):
            self.export()

    def test_exports_child_only_when_parent_evidence_matches(self) -> None:
        brief = next(item for item in self.briefs if item["id"] == "illustration-character")
        parent_source = build_run_source(self.temp_path / "parent-runs", brief)
        parent_manifest = read_json(parent_source / "manifest.json")
        parent_metadata = self.temp_path / "parent-metadata.json"
        write_json(parent_metadata, observed_metadata(str(brief["id"])))
        parent_destination = self.evidence_root / "runs" / brief["id"]
        export_run(
            parent_source,
            parent_destination,
            FIXTURE_PATH,
            parent_metadata,
            str(parent_manifest["run_id"]),
            None,
        )
        parent_manifest_before = (parent_destination / "manifest.json").read_bytes()

        child_source = build_run_source(self.temp_path / "child-runs", brief, revision=True)
        child_manifest = read_json(child_source / "manifest.json")
        child_metadata = self.temp_path / "child-metadata.json"
        write_json(child_metadata, observed_metadata(str(brief["id"])))
        child_destination = self.evidence_root / "revisions" / brief["id"]
        result = export_run(
            child_source,
            child_destination,
            FIXTURE_PATH,
            child_metadata,
            str(child_manifest["run_id"]),
            parent_destination / "evidence.json",
        )

        self.assertTrue(result["ok"])
        self.assertTrue((child_destination / "parent-evidence.json").is_file())
        self.assertEqual((parent_destination / "manifest.json").read_bytes(), parent_manifest_before)


def _path_values(value: object, key: str | None = None) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            found.extend(_path_values(child, child_key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_path_values(child, key))
    elif isinstance(value, str) and key in {"path", "mask_path", "overlay_path"}:
        found.append(value)
    return found


def _public_route() -> dict[str, object]:
    return {
        "authorization_scope": "public_evidence",
        "model_id": "approved-local-model",
        "backend": "webui",
        "endpoint_identity": "endpoint:private",
        "identity_token": "model:private",
        "identity_strength": "cryptographic",
        "sha256": "a" * 64,
        "workflow_template_id": None,
        "workflow_template_version": None,
        "prompt_compiler_id": "sd15-tags-v1",
        "prompt_compiler_version": 1,
    }


if __name__ == "__main__":
    unittest.main()
