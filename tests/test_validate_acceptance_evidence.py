from __future__ import annotations

import copy
import json
import shutil
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
    build_two_stage_run_source,
    edit_json,
    public_route,
    read_json,
    rgb_png_bytes,
    sha256_file,
    write_json,
)


class AcceptanceEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.two_stage_fixture_index = 0

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def build_two_stage_package(self) -> tuple[Path, Path]:
        self.two_stage_fixture_index += 1
        fixture_id = self.two_stage_fixture_index
        briefs = read_json(FIXTURE_PATH)
        brief = next(item for item in briefs if item["id"] == "ui-section")
        source, authority, metadata = build_two_stage_run_source(
            self.temp_path / f"two-stage-source-{fixture_id}",
            brief,
        )
        root = self.temp_path / f"two-stage-evidence-{fixture_id}"
        package = root / "runs" / str(brief["id"])
        package.mkdir(parents=True)
        write_json(root / "acceptance-authority.json", authority)
        for name in (
            "round-01-base.png",
            "round-01-mask.png",
            "round-01.png",
            "round-01-preview.jpg",
            "final.png",
        ):
            shutil.copyfile(source / name, package / name)

        manifest = read_json(source / "manifest.json")
        public = copy_public_route(manifest["request"]["route"])
        manifest["request"]["route"] = public
        write_json(package / "brief.json", brief)
        write_json(package / "manifest.json", manifest)
        write_json(package / "mcp-final-result.json", read_json(source / "mcp-final-result.json"))
        selected = manifest["rounds"][0]
        write_json(package / "evidence.json", {
            "schema_version": 1,
            "evidence_class": "real-codex-mcp-run",
            "brief_id": brief["id"],
            "run_id": manifest["run_id"],
            "host": metadata["host"],
            "profile": brief["profile"],
            "style": brief["style"],
            "backend": metadata["backend"],
            "model": metadata["model"],
            "route": public,
            "environment": metadata["environment"],
            "started_at": manifest["attempts"][0]["started_at"],
            "completed_at": manifest["final"]["finalized_at"],
            "files": {
                "brief": "brief.json",
                "manifest": "manifest.json",
                "mcp_final_result": "mcp-final-result.json",
                "final": "final.png",
            },
            "selected_round": 1,
            "quality_status": "accepted",
            "known_limitations": metadata["known_limitations"],
            "decision_summary": metadata["decision_summary"],
            "two_stage": {
                "base": artifact_reference(selected["stages"][0]["image"]),
                "mask": artifact_reference(selected["mask_artifact"]),
                "final": artifact_reference(selected["stages"][1]["image"]),
                "control_sha256": selected["backend_result"]["control_sha256"],
                "subject_seed": selected["backend_result"]["subject_seed"],
                "stage_budget": manifest["stage_budget"],
                "pixel_preservation": selected["pixel_preservation"],
            },
        })
        return root, package

    def test_accepts_complete_real_matrix(self) -> None:
        root = build_complete_matrix(self.temp_path)
        result = validate_evidence(root, FIXTURE_PATH, strict=True)
        self.assertEqual(result["run_count"], 9)
        self.assertEqual(result["revision_count"], 3)
        self.assertEqual(result["profiles"], 3)
        self.assertTrue(result["release_ready"])
        self.assertTrue(result["ok"])

    def test_accepts_exact_two_stage_package(self) -> None:
        root, _ = self.build_two_stage_package()

        try:
            result = validate_evidence(root, FIXTURE_PATH, strict=False)
        except EvidenceError as error:
            self.fail(f"Exact two-stage evidence should validate: {error}")

        self.assertEqual(result["run_count"], 1)
        self.assertTrue(result["ok"])

    def test_two_stage_validator_rejects_missing_extra_and_changed_stage_files(self) -> None:
        for case in ("missing", "extra", "changed"):
            root, package = self.build_two_stage_package()
            if case == "missing":
                (package / "round-01-base.png").unlink()
                expected = "evidence_file_missing"
            elif case == "extra":
                (package / "unreferenced.png").write_bytes(b"extra")
                expected = "unexpected_evidence_file"
            else:
                (package / "round-01-base.png").write_bytes(b"changed")
                expected = "artifact_hash_mismatch"
            with self.subTest(case=case), self.assertRaisesRegex(EvidenceError, expected):
                validate_evidence(root, FIXTURE_PATH, strict=False)
            shutil.rmtree(root)

    def test_two_stage_validator_rejects_mask_leak_with_matching_changed_hash(self) -> None:
        root, package = self.build_two_stage_package()
        layout = read_json(package / "manifest.json")["request"]["constraints"]["two_stage_layout"]
        width = layout["canvas"]["width"]
        height = layout["canvas"]["height"]
        pixels = bytearray(width * height * 3)
        subject = layout["subject_mask_rect"]
        for y in range(subject["y"], subject["y"] + subject["height"]):
            for x in range(subject["x"], subject["x"] + subject["width"]):
                offset = (y * width + x) * 3
                pixels[offset:offset + 3] = b"\xff\xff\xff"
        pixels[0:3] = b"\xff\xff\xff"
        mask_path = package / "round-01-mask.png"
        mask_path.write_bytes(rgb_png_bytes(width, height, bytes(pixels)))
        changed_hash = sha256_file(mask_path)
        manifest = read_json(package / "manifest.json")
        manifest["rounds"][0]["mask_artifact"]["sha256"] = changed_hash
        write_json(package / "manifest.json", manifest)
        evidence = read_json(package / "evidence.json")
        evidence["two_stage"]["mask"]["sha256"] = changed_hash
        write_json(package / "evidence.json", evidence)

        with self.assertRaisesRegex(EvidenceError, "invalid_two_stage_mask"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_two_stage_validator_rejects_nonzero_or_inconsistent_pixel_report(self) -> None:
        for case in ("nonzero", "inconsistent"):
            root, package = self.build_two_stage_package()
            manifest = read_json(package / "manifest.json")
            evidence = read_json(package / "evidence.json")
            if case == "nonzero":
                manifest["rounds"][0]["pixel_preservation"]["mismatched_pixels"] = 1
                evidence["two_stage"]["pixel_preservation"]["mismatched_pixels"] = 1
                expected = "nonzero_pixel_mismatch"
            else:
                evidence["two_stage"]["pixel_preservation"]["checked_pixels"] += 1
                expected = "pixel_report_mismatch"
            write_json(package / "manifest.json", manifest)
            write_json(package / "evidence.json", evidence)
            with self.subTest(case=case), self.assertRaisesRegex(EvidenceError, expected):
                validate_evidence(root, FIXTURE_PATH, strict=False)
            shutil.rmtree(root)

    def test_two_stage_validator_recomputes_control_digest(self) -> None:
        root, package = self.build_two_stage_package()
        manifest = read_json(package / "manifest.json")
        evidence = read_json(package / "evidence.json")
        changed = "f" * 64
        manifest["request"]["route"]["control_sha256"] = changed
        manifest["rounds"][0]["backend_result"]["control_sha256"] = changed
        evidence["route"]["control_sha256"] = changed
        evidence["two_stage"]["control_sha256"] = changed
        write_json(package / "manifest.json", manifest)
        write_json(package / "evidence.json", evidence)

        with self.assertRaisesRegex(EvidenceError, "invalid_two_stage_evidence"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_two_stage_validator_recomputes_subject_seed(self) -> None:
        root, package = self.build_two_stage_package()
        manifest = read_json(package / "manifest.json")
        evidence = read_json(package / "evidence.json")
        manifest["rounds"][0]["stages"][1]["seed"] = 44
        manifest["rounds"][0]["backend_result"]["subject_seed"] = 44
        evidence["two_stage"]["subject_seed"] = 44
        write_json(package / "manifest.json", manifest)
        write_json(package / "evidence.json", evidence)

        with self.assertRaisesRegex(EvidenceError, "invalid_two_stage_evidence"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_validator_rejects_two_stage_manifest_with_standard_route(self) -> None:
        root = build_complete_matrix(self.temp_path)
        package = root / "runs" / "ui-section"
        manifest = read_json(package / "manifest.json")
        manifest["request"]["workflow_template_id"] = "sdxl-two-stage-copy-subject"
        write_json(package / "manifest.json", manifest)

        with self.assertRaisesRegex(EvidenceError, "route_authority_mismatch"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_private_backend_model_id_exception_is_limited_to_public_route_bundle(self) -> None:
        root = build_complete_matrix(self.temp_path)
        package = root / "runs" / "ui-section"
        manifest = read_json(package / "manifest.json")
        manifest["request"]["untrusted"] = {
            "component_bundle": {
                "components": [{"backend_model_id": "private-checkpoint.safetensors"}],
            },
        }
        write_json(package / "manifest.json", manifest)

        with self.assertRaisesRegex(EvidenceError, "private_evidence_value"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_two_stage_validator_rejects_partial_and_outside_stage_references(self) -> None:
        root, package = self.build_two_stage_package()
        manifest = read_json(package / "manifest.json")
        manifest["state"] = "partial"
        write_json(package / "manifest.json", manifest)
        with self.assertRaisesRegex(EvidenceError, "partial_evidence_forbidden"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

        shutil.rmtree(root)
        root, package = self.build_two_stage_package()
        manifest = read_json(package / "manifest.json")
        manifest["rounds"][0]["stages"][0]["image"]["path"] = "../outside.png"
        write_json(package / "manifest.json", manifest)
        evidence = read_json(package / "evidence.json")
        evidence["two_stage"]["base"]["path"] = "../outside.png"
        write_json(package / "evidence.json", evidence)
        with self.assertRaisesRegex(EvidenceError, "evidence_path_escape"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_two_stage_validator_never_accepts_base_or_mask_as_final_image(self) -> None:
        for role in ("base", "mask"):
            root, package = self.build_two_stage_package()
            manifest = read_json(package / "manifest.json")
            evidence = read_json(package / "evidence.json")
            supporting = evidence["two_stage"][role]
            final_record = manifest["final"]
            final_record["path"] = supporting["path"]
            final_record["image"] = {
                **(
                    manifest["rounds"][0]["stages"][0]["image"]
                    if role == "base"
                    else manifest["rounds"][0]["mask_artifact"]
                )
            }
            evidence["files"]["final"] = supporting["path"]
            mcp = read_json(package / "mcp-final-result.json")
            mcp["final"] = final_record
            write_json(package / "manifest.json", manifest)
            write_json(package / "evidence.json", evidence)
            write_json(package / "mcp-final-result.json", mcp)
            with self.subTest(role=role), self.assertRaisesRegex(EvidenceError, "invalid_final_evidence"):
                validate_evidence(root, FIXTURE_PATH, strict=False)
            shutil.rmtree(root)

    def test_standard_package_rejects_two_stage_evidence_object(self) -> None:
        root = build_complete_matrix(self.temp_path)
        package = root / "runs" / "ui-hero"
        evidence = read_json(package / "evidence.json")
        evidence["two_stage"] = {}
        write_json(package / "evidence.json", evidence)

        with self.assertRaisesRegex(EvidenceError, "invalid_evidence_shape"):
            validate_evidence(root, FIXTURE_PATH, strict=False)

    def test_run_evidence_schema_defines_exact_optional_two_stage_object(self) -> None:
        schema = read_json(ROOT / "docs" / "evidence" / "schemas" / "run-evidence.schema.json")

        self.assertIn("two_stage", schema["properties"])
        two_stage = schema["properties"]["two_stage"]
        self.assertFalse(two_stage["additionalProperties"])
        self.assertEqual(set(two_stage["required"]), {
            "base", "mask", "final", "control_sha256", "subject_seed",
            "stage_budget", "pixel_preservation",
        })
        self.assertIn("control_sha256", schema["properties"]["route"]["properties"])

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

    def test_repository_authority_pins_approved_sdxl_comfyui_bundle(self) -> None:
        authority = validate_authority(
            ROOT / "docs" / "evidence" / "acceptance-authority.json",
            FIXTURE_PATH,
        )

        self.assertEqual(
            authority["backend"],
            {"type": "comfyui", "implementation": "ComfyUI", "local": True},
        )
        self.assertEqual(authority["repository_license"], "MIT")
        self.assertEqual(authority["copyright_holder"], "Capricorn")
        self.assertEqual(
            authority["installation_or_download"],
            {"approved": False, "items": []},
        )
        self.assertEqual(len(authority["models"]), 1)
        model = authority["models"][0]
        self.assertEqual(model["id"], "local:1a4a27ae037d08ad44e98772")
        self.assertEqual(
            model["source"],
            "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
        )
        self.assertEqual(model["license_id"], "CreativeML Open RAIL++-M")
        self.assertEqual(
            model["license_url"],
            "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
        )
        self.assertEqual(
            model["expected_storage"],
            "existing local ComfyUI checkpoint directory",
        )
        self.assertEqual(
            model["sha256"],
            "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b",
        )
        self.assertTrue(model["use_approved"])
        self.assertFalse(model["download_approved"])
        self.assertEqual(model["output_redistribution_status"], "approved")
        self.assertEqual(
            model["workflow"],
            {
                "template_id": "sdxl-txt2img",
                "template_version": 1,
                "sha256": "05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e",
            },
        )
        self.assertEqual(
            model["component_bundle_sha256"],
            "ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62",
        )
        self.assertEqual(
            model["components"],
            [{
                "role": "primary_model",
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
                "backend_model_id": "sd_xl_base_1.0.safetensors",
                "filesystem_identity_token": "model:1a4a27ae037d08ad44e987720d07df0910fff0e1d3210378e6a4886cfc4f97a5",
                "sha256": "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b",
                "byte_size": 6938078334,
                "source": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
                "license_id": "CreativeML Open RAIL++-M",
                "license_url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
                "output_redistribution_status": "approved",
            }],
        )

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


def copy_public_route(route: dict[str, object]) -> dict[str, object]:
    keys = {
        "authorization_scope",
        "backend",
        "model_id",
        "sha256",
        "identity_strength",
        "workflow_template_id",
        "workflow_template_version",
        "prompt_compiler_id",
        "prompt_compiler_version",
        "component_bundle",
        "component_bundle_sha256",
        "control_sha256",
    }
    return {
        key: copy.deepcopy(value)
        for key, value in route.items()
        if key in keys
    }


def artifact_reference(value: dict[str, object]) -> dict[str, object]:
    return {"path": value["path"], "sha256": value["sha256"]}


if __name__ == "__main__":
    unittest.main()
