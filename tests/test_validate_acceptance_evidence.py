from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.model_identity import build_component_bundle  # noqa: E402
from validate_acceptance_evidence import (  # noqa: E402
    EvidenceError,
    _validate_public_route,
    validate_authority,
    validate_evidence,
)
from tests.acceptance_evidence_helpers import (  # noqa: E402
    FIXTURE_PATH,
    approved_authority,
    build_complete_matrix,
    edit_json,
    public_route,
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

    def test_comfyui_authority_and_route_bind_exact_component_bundle(self) -> None:
        identities = [
            {
                "role": role,
                "loader_class": loader_class,
                "loader_input": loader_input,
                "backend_model_id": backend_name,
                "filesystem_identity_token": "model:" + marker * 64,
                "sha256": marker * 64,
                "byte_size": size,
            }
            for role, loader_class, loader_input, backend_name, marker, size in (
                ("primary_model", "UNETLoader", "unet_name", "z-image.safetensors", "a", 100),
                ("text_encoder", "CLIPLoader", "clip_name", "qwen.safetensors", "b", 200),
                ("vae", "VAELoader", "vae_name", "ae.safetensors", "c", 300),
            )
        ]
        workflow = {
            "template_id": "z-image-turbo-txt2img",
            "template_version": 1,
            "sha256": "d" * 64,
        }
        bundle = build_component_bundle(identities, workflow)
        authority = approved_authority()
        authority["backend"] = {"type": "comfyui", "implementation": "ComfyUI", "local": True}
        authority["models"][0].update({
            "component_bundle_sha256": bundle["bundle_sha256"],
            "workflow": workflow,
            "components": [
                {
                    **identity,
                    "source": f"https://models.example/{identity['role']}",
                    "license_id": "Apache-2.0",
                    "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
                    "output_redistribution_status": "approved",
                }
                for identity in identities
            ],
        })
        path = self.temp_path / "authority.json"
        write_json(path, authority)
        validated = validate_authority(path, FIXTURE_PATH)
        route = {
            **public_route(),
            "backend": "comfyui",
            "workflow_template_id": workflow["template_id"],
            "workflow_template_version": workflow["template_version"],
            "component_bundle": bundle,
            "component_bundle_sha256": bundle["bundle_sha256"],
        }

        self.assertEqual(_validate_public_route(route, validated), route)
        route["component_bundle"] = {
            **bundle,
            "components": [{**bundle["components"][0], "sha256": "e" * 64}, *bundle["components"][1:]],
        }
        with self.assertRaisesRegex(EvidenceError, "route_authority_mismatch"):
            _validate_public_route(route, validated)

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
