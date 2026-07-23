from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ConflictError, ValidationError  # noqa: E402
from local_gpu_imagegen.model_catalog import ModelCatalog, REPOSITORY_REQUIRED  # noqa: E402
from local_gpu_imagegen.model_identity import (  # noqa: E402
    build_component_bundle,
    identity_token,
    validate_discovery_record,
)
from local_gpu_imagegen.regional_layout import REGIONAL_TEMPLATE_ID  # noqa: E402
from local_gpu_imagegen.two_stage_layout import (  # noqa: E402
    TWO_STAGE_LAYOUT_MODE,
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
)


def discovery_record(
    name: str,
    *,
    digest: str | None,
    modified_ns: int | None = None,
) -> dict[str, object]:
    record = validate_discovery_record({
        "backend": "webui",
        "endpoint_identity": "endpoint:webui",
        "backend_model_id": name,
        "format": ".safetensors",
        "byte_size": 1024 if modified_ns is not None else None,
        "modified_ns": modified_ns,
        "sha256": digest,
        "identity_strength": "cryptographic" if digest else "backend_binding",
        "metadata": {},
    })
    record["identity_token"] = identity_token(record)
    return record


def trust_record(
    record: dict[str, object],
    *,
    catalog_id: str,
    scope: str,
    evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "catalog_id": catalog_id,
        "identity_token": identity_token(record),
        "identity_strength": record["identity_strength"],
        "scope": scope,
        "identity_record": copy.deepcopy(record),
        "capabilities": {
            "model_family": "unknown",
            "prompt_dialect": "natural-v1",
            "operations": ["txt2img", "inpaint"],
            "minimum_dimension": 256,
            "maximum_dimension": 1536,
            "minimum_vram_gb": 6,
            "negative_prompt": "supported",
            "affinity": ["illustration"],
            "recommended": {
                "resolution": {"width": 768, "height": 512},
                "steps": 20,
                "guidance": 7.0,
                "sampler": "euler",
                "scheduler": "normal",
            },
        },
        "workflow_binding": None,
        "preference": 0,
        "public_metadata": {
            "source": "https://example.invalid/model",
            "license_id": "test-license",
            "license_url": "https://example.invalid/license",
            "output_redistribution_status": "approved",
        } if scope == "public_candidate" else None,
        "limitations": [],
        "evidence": evidence or [{"level": "declared"}],
        "approved_at": "2026-07-21T00:00:00Z",
    }


def repository_model() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "repo/anime",
        "kind": "model",
        "source": "local-webui",
        "sha256": "a" * 64,
        "license_id": "approved-test",
        "license_url": "https://example.invalid/license",
        "license_status": "approved",
        "output_redistribution_status": "approved",
        "backends": ["webui"],
        "local_discovery_names": ["repo-anime.safetensors"],
        "strengths": ["test"],
        "limitations": [],
        "use_cases": ["standalone-illustration"],
        "styles": ["anime"],
        "recommended": {
            "resolution": {"width": 768, "height": 512},
            "steps": 24,
            "guidance": 5.5,
            "sampler": "euler",
            "scheduler": "normal",
        },
        "known_local": True,
        "enabled": True,
        "model_family": "sd15",
        "prompt_dialect": "sd15-tags-v1",
        "capabilities": {
            "operations": ["txt2img", "img2img", "inpaint"],
            "minimum_dimension": 256,
            "maximum_dimension": 1536,
            "minimum_vram_gb": 6,
            "negative_prompt": "supported",
        },
        "affinity": ["anime", "illustration"],
        "evidence": {
            "level": "declared",
            "operations": ["txt2img", "img2img", "inpaint"],
        },
    }


class FakeTrustRegistry:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records
        self.observations: list[tuple[str, str, str, str]] = []

    def list_records(self) -> list[dict[str, object]]:
        return copy.deepcopy(self.records)

    def record_observation(
        self,
        model_id: str,
        token: str,
        operation: str,
        run_id: str,
    ) -> None:
        self.observations.append((model_id, token, operation, run_id))


class FakeWorkflows:
    def inspect_shipped(
        self,
        template_id: str,
        model_id: str,
        operation: str,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        return self.resolve(template_id, model_id, operation, parameters)

    def resolve(
        self,
        template_id: str,
        _model_id: str,
        operation: str,
        _parameters: dict[str, object],
    ) -> dict[str, object]:
        return {
            "template_id": template_id,
            "template_version": 1,
            "operation": operation,
            "workflow_sha256": "d" * 64,
        }


class ModelCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.models_root = Path(self.temporary_directory.name) / "models"
        self.models_root.mkdir()
        (self.models_root / "repo.json").write_text(
            json.dumps(repository_model()),
            encoding="utf-8",
        )
        self.repo_model = discovery_record("repo-anime.safetensors", digest="a" * 64)
        self.backend_bound = discovery_record("private-bound.safetensors", digest=None)
        self.crypto_model = discovery_record(
            "private-crypto.safetensors",
            digest="b" * 64,
            modified_ns=100,
        )
        self.inventory = [self.repo_model, self.backend_bound, self.crypto_model]
        self.trust = FakeTrustRegistry([
            trust_record(
                self.backend_bound,
                catalog_id="local:backend-bound",
                scope="private",
            ),
            trust_record(
                self.crypto_model,
                catalog_id="local:crypto",
                scope="public_candidate",
                evidence=[
                    {"level": "declared"},
                    {"level": "observed", "operation": "txt2img", "run_id": "run-1"},
                ],
            ),
        ])
        self.readiness = {"available_backends": ["webui"]}
        self.catalog = ModelCatalog(
            self.models_root,
            lambda: self.inventory,
            self.trust,
            lambda: self.readiness,
            FakeWorkflows(),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def two_stage_layout() -> dict[str, object]:
        return {
            "mode": TWO_STAGE_LAYOUT_MODE,
            "canvas": {"width": 640, "height": 320},
            "copy_protected_rect": {"x": 0, "y": 0, "width": 224, "height": 320},
            "subject_mask_rect": {"x": 304, "y": 16, "width": 320, "height": 288},
            "feather_pixels": 0,
            "vae_grow_mask_by": 0,
        }

    def install_sdxl_variants(self) -> None:
        filesystem = validate_discovery_record({
            "backend": "filesystem",
            "endpoint_identity": "filesystem:sdxl",
            "backend_model_id": "sd_xl_base_1.0.safetensors",
            "format": ".safetensors",
            "byte_size": 2048,
            "modified_ns": 123,
            "sha256": "c" * 64,
            "identity_strength": "cryptographic",
            "metadata": {},
        })
        filesystem["identity_token"] = identity_token(filesystem)
        comfy = validate_discovery_record({
            "backend": "comfyui",
            "endpoint_identity": "endpoint:comfyui",
            "backend_model_id": "sd_xl_base_1.0.safetensors",
            "format": ".safetensors",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
            },
        })
        comfy["identity_token"] = identity_token(comfy)
        self.inventory.extend((filesystem, comfy))
        self.readiness["available_backends"].append("comfyui")

        for index, template_id in enumerate((
            "sdxl-txt2img",
            REGIONAL_TEMPLATE_ID,
            TWO_STAGE_TEMPLATE_ID,
        )):
            bundle = build_component_bundle(
                [{
                    "role": "primary_model",
                    "loader_class": "CheckpointLoaderSimple",
                    "loader_input": "ckpt_name",
                    "backend_model_id": "sd_xl_base_1.0.safetensors",
                    "filesystem_identity_token": filesystem["identity_token"],
                    "sha256": "c" * 64,
                    "byte_size": 2048,
                }],
                {
                    "template_id": template_id,
                    "template_version": 1,
                    "sha256": "d" * 64,
                },
            )
            trusted = trust_record(
                filesystem,
                catalog_id=f"local:sdxl-variant-{index}",
                scope="public_candidate",
            )
            trusted["workflow_binding"] = {
                "backend": "comfyui",
                "backend_model_id": "sd_xl_base_1.0.safetensors",
                "endpoint_identity": "endpoint:comfyui",
                "backend_identity_token": comfy["identity_token"],
                "template_id": template_id,
                "template_version": 1,
                "workflow_sha256": "d" * 64,
                "component_bundle_sha256": bundle["bundle_sha256"],
            }
            if template_id == REGIONAL_TEMPLATE_ID:
                trusted["capabilities"]["regional_layout_modes"] = [
                    "copy-subject-v1"
                ]
            elif template_id == TWO_STAGE_TEMPLATE_ID:
                trusted["capabilities"]["two_stage_layout_modes"] = [
                    TWO_STAGE_LAYOUT_MODE
                ]
                trusted["workflow_binding"]["control_sha256"] = build_control_identity(
                    self.two_stage_layout(),
                    "d" * 64,
                    "base-subject-v1",
                )
            trusted["component_bundle"] = bundle
            trusted["public_metadata"]["components"] = [{
                "role": "primary_model",
                "sha256": "c" * 64,
                "source": "https://example.invalid/component",
                "license_id": "test-license",
                "license_url": "https://example.invalid/license",
                "output_redistribution_status": "approved",
            }]
            trusted["capabilities"]["operations"] = ["txt2img"]
            self.trust.records.append(trusted)

    def test_catalog_merges_repository_identity_without_promoting_evidence(self) -> None:
        model = self.catalog.resolve("repo/anime", "public_evidence")

        self.assertEqual(model["identity_token"], identity_token(self.repo_model))
        self.assertEqual(model["identity_strength"], "cryptographic")
        self.assertEqual(model["backend"], "webui")
        self.assertEqual(model["evidence_level"], "declared")
        self.assertEqual(model["prompt_compiler_id"], "sd15-tags-v1")
        self.assertIsNone(model["workflow_template_id"])
        self.assertEqual(
            identity_token(validate_discovery_record(model)),
            model["identity_token"],
        )

    def test_standard_regional_and_two_stage_variants_coexist_for_one_model(self) -> None:
        self.install_sdxl_variants()

        variants = [
            item
            for item in self.catalog.list_models("public_evidence")
            if item["backend_model_id"] == "sd_xl_base_1.0.safetensors"
        ]

        self.assertEqual(
            {item["workflow_template_id"] for item in variants},
            {"sdxl-txt2img", REGIONAL_TEMPLATE_ID, TWO_STAGE_TEMPLATE_ID},
        )
        two_stage = next(
            item for item in variants
            if item["workflow_template_id"] == TWO_STAGE_TEMPLATE_ID
        )
        self.assertEqual(
            two_stage["control_sha256"],
            build_control_identity(
                self.two_stage_layout(),
                "d" * 64,
                "base-subject-v1",
            ),
        )
        self.assertIsNone(next(
            item for item in variants
            if item["workflow_template_id"] == "sdxl-txt2img"
        )["control_sha256"])

    def test_locked_two_stage_route_rejects_control_digest_drift(self) -> None:
        self.install_sdxl_variants()
        model = next(
            item
            for item in self.catalog.list_models("public_evidence")
            if item["workflow_template_id"] == TWO_STAGE_TEMPLATE_ID
        )
        route = {
            "model_id": model["id"],
            "authorization_scope": "public_evidence",
            **{
                field: copy.deepcopy(model[field])
                for field in (
                    "identity_token",
                    "identity_strength",
                    "backend",
                    "endpoint_identity",
                    "workflow_template_id",
                    "workflow_template_version",
                    "component_bundle_sha256",
                    "control_sha256",
                )
            },
        }
        trust = next(
            item
            for item in self.trust.records
            if (item.get("workflow_binding") or {}).get("template_id")
            == TWO_STAGE_TEMPLATE_ID
        )
        trust["workflow_binding"]["control_sha256"] = "f" * 64

        with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            self.catalog.verify_locked_route(route)

    def test_catalog_separates_private_and_public_candidate_scope(self) -> None:
        private = {item["id"] for item in self.catalog.list_models("private")}
        public = {item["id"] for item in self.catalog.list_models("public_evidence")}

        self.assertIn("local:backend-bound", private)
        self.assertNotIn("local:backend-bound", public)
        self.assertIn("local:crypto", private)
        self.assertIn("local:crypto", public)
        crypto = self.catalog.resolve("local:crypto", "private")
        self.assertEqual(crypto["evidence_level"], "observed")
        self.assertNotEqual(crypto["evidence_level"], "benchmarked")

    def test_trusted_capabilities_normalize_optional_regional_modes(self) -> None:
        self.trust.records[0]["capabilities"]["regional_layout_modes"] = [
            "copy-subject-v1"
        ]

        regional = self.catalog.resolve("local:backend-bound", "private")
        legacy = self.catalog.resolve("local:crypto", "private")

        self.assertEqual(
            regional["capabilities"]["regional_layout_modes"],
            ["copy-subject-v1"],
        )
        self.assertEqual(legacy["capabilities"]["regional_layout_modes"], [])

        self.trust.records[0]["capabilities"]["regional_layout_modes"] = [
            "arbitrary-regions"
        ]
        with self.assertRaisesRegex(ValidationError, "invalid_model_capabilities"):
            self.catalog.list_models("private")

    def test_unready_or_untrusted_inventory_is_not_eligible(self) -> None:
        self.readiness["available_backends"] = []
        self.assertEqual(self.catalog.list_models("private"), [])
        self.readiness["available_backends"] = ["webui"]
        self.trust.records.clear()

        self.assertEqual(
            [item["id"] for item in self.catalog.list_models("private")],
            ["repo/anime"],
        )

    def test_unfingerprinted_stage_one_candidates_do_not_break_catalog(self) -> None:
        self.inventory.append({
            "candidate_id": "candidate:index-only",
            "source_type": "filesystem",
            "resolved_root": "D:/models",
            "local_path": "D:/models/index-only.safetensors",
            "relative_path": "index-only.safetensors",
            "filename": "index-only.safetensors",
            "format": ".safetensors",
            "byte_size": 1024,
            "modified_ns": 123,
            "metadata": {},
            "sha256": None,
            "identity_strength": None,
            "trusted": False,
        })

        ids = [item["id"] for item in self.catalog.list_models("private")]

        self.assertIn("repo/anime", ids)
        self.assertNotIn("candidate:index-only", ids)

    def test_catalog_detects_drift_before_route_use(self) -> None:
        model = self.catalog.resolve("local:crypto", "private")
        route = {
            "model_id": model["id"],
            "authorization_scope": "private",
            "identity_token": model["identity_token"],
            "identity_strength": model["identity_strength"],
            "backend": model["backend"],
            "endpoint_identity": model["endpoint_identity"],
            "workflow_template_id": model["workflow_template_id"],
            "workflow_template_version": model["workflow_template_version"],
        }
        self.crypto_model["modified_ns"] = 101

        with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            self.catalog.verify_locked_route(route)

    def test_resolve_rejects_invalid_scope_or_ineligible_id(self) -> None:
        with self.assertRaisesRegex(ValidationError, "invalid_authorization_scope"):
            self.catalog.list_models("release")
        with self.assertRaisesRegex(ValidationError, "model_not_eligible"):
            self.catalog.resolve("missing", "private")

    def test_local_observation_delegates_without_promoting_repository_claims(self) -> None:
        model = self.catalog.resolve("local:crypto", "private")

        self.catalog.record_observation(
            model["id"],
            model["identity_token"],
            "txt2img",
            "run-2",
        )
        self.catalog.record_observation(
            "repo/anime",
            identity_token(self.repo_model),
            "txt2img",
            "run-3",
        )

        self.assertEqual(
            self.trust.observations,
            [("local:crypto", model["identity_token"], "txt2img", "run-2")],
        )

    def test_filesystem_fingerprint_binds_to_exact_comfyui_endpoint_and_model(self) -> None:
        filesystem = validate_discovery_record({
            "backend": "filesystem",
            "endpoint_identity": "filesystem:root",
            "backend_model_id": "anything-v5.safetensors",
            "format": ".safetensors",
            "byte_size": 2048,
            "modified_ns": 123,
            "sha256": "c" * 64,
            "identity_strength": "cryptographic",
            "metadata": {},
        })
        filesystem["identity_token"] = identity_token(filesystem)
        comfy = validate_discovery_record({
            "backend": "comfyui",
            "endpoint_identity": "endpoint:comfyui",
            "backend_model_id": "anything-v5.safetensors",
            "format": ".safetensors",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
            },
        })
        comfy["identity_token"] = identity_token(comfy)
        trusted = trust_record(
            filesystem,
            catalog_id="local:filesystem-comfy",
            scope="public_candidate",
        )
        trusted["workflow_binding"] = {
            "backend": "comfyui",
            "backend_model_id": "anything-v5.safetensors",
            "endpoint_identity": "endpoint:comfyui",
            "backend_identity_token": comfy["identity_token"],
            "template_id": "sd15-txt2img",
            "template_version": 1,
            "workflow_sha256": "d" * 64,
        }
        trusted["component_bundle"] = build_component_bundle(
            [{
                "role": "primary_model",
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
                "backend_model_id": "anything-v5.safetensors",
                "filesystem_identity_token": filesystem["identity_token"],
                "sha256": "c" * 64,
                "byte_size": 2048,
            }],
            {
                "template_id": "sd15-txt2img",
                "template_version": 1,
                "sha256": "d" * 64,
            },
        )
        trusted["workflow_binding"]["component_bundle_sha256"] = trusted["component_bundle"]["bundle_sha256"]
        trusted["public_metadata"]["components"] = [{
            "role": "primary_model",
            "sha256": "c" * 64,
            "source": "https://example.invalid/component",
            "license_id": "test-license",
            "license_url": "https://example.invalid/license",
            "output_redistribution_status": "approved",
        }]
        trusted["capabilities"]["operations"] = ["txt2img"]
        self.inventory.extend((filesystem, comfy))
        self.trust.records.append(trusted)
        self.readiness["available_backends"].append("comfyui")

        model = self.catalog.resolve("local:filesystem-comfy", "public_evidence")

        self.assertEqual(model["backend"], "comfyui")
        self.assertEqual(model["endpoint_identity"], "endpoint:comfyui")
        self.assertEqual(model["backend_model_id"], "anything-v5.safetensors")
        self.assertEqual(model["identity_strength"], "cryptographic")
        self.assertEqual(model["sha256"], "c" * 64)
        self.assertEqual(model["workflow_template_id"], "sd15-txt2img")
        self.assertEqual(
            model["component_bundle_sha256"],
            trusted["component_bundle"]["bundle_sha256"],
        )
        self.assertEqual(
            identity_token(validate_discovery_record(model)),
            model["identity_token"],
        )

        self.catalog.record_observation(
            model["id"],
            model["identity_token"],
            "txt2img",
            "run-comfy",
        )
        self.assertEqual(
            self.trust.observations[-1][1],
            filesystem["identity_token"],
        )

        self.inventory.remove(filesystem)
        with self.assertRaisesRegex(ValidationError, "model_not_eligible"):
            self.catalog.resolve("local:filesystem-comfy", "public_evidence")

    def test_shipped_schema_and_records_expose_exact_routing_metadata(self) -> None:
        schema = json.loads(
            (ROOT / "profiles" / "schemas" / "model.schema.json").read_text(
                encoding="utf-8"
            )
        )
        routing_fields = {
            "model_family",
            "prompt_dialect",
            "capabilities",
            "affinity",
            "evidence",
        }

        self.assertEqual(set(schema["required"]), set(REPOSITORY_REQUIRED))
        self.assertTrue(routing_fields <= set(schema["required"]))
        for field in ("capabilities", "evidence"):
            self.assertFalse(schema["properties"][field]["additionalProperties"])
        for path in sorted((ROOT / "profiles" / "models").glob("*.json")):
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(routing_fields <= set(document))
                self.assertEqual(document["evidence"]["level"], "declared")

    def test_sdxl_repository_record_stays_disabled_as_safe_default(self) -> None:
        path = ROOT / "profiles" / "models" / "sdxl-base-1.0.json"
        self.assertTrue(path.exists(), "Reviewed SDXL model record is missing.")

        model = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(model["id"], "stabilityai/stable-diffusion-xl-base-1.0")
        self.assertEqual(
            model["sha256"],
            "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b",
        )
        self.assertEqual(model["backends"], ["comfyui"])
        self.assertEqual(
            model["local_discovery_names"],
            ["sd_xl_base_1.0.safetensors"],
        )
        self.assertTrue(model["known_local"])
        self.assertFalse(model["enabled"])
        self.assertEqual(model["license_status"], "requires_user_review")
        self.assertEqual(
            model["output_redistribution_status"],
            "requires_user_review",
        )
        self.assertEqual(model["model_family"], "sdxl")
        self.assertEqual(model["prompt_dialect"], "natural-v1")
        self.assertEqual(model["workflow_template_id"], "sdxl-txt2img")
        self.assertEqual(model["workflow_template_version"], 1)
        self.assertEqual(model["capabilities"]["operations"], ["txt2img"])
        self.assertEqual(
            model["recommended"],
            {
                "resolution": {"width": 1024, "height": 1024},
                "steps": 30,
                "guidance": 7.0,
                "sampler": "dpmpp_2m",
                "scheduler": "karras",
            },
        )
        self.assertNotRegex(json.dumps(model), r"[A-Za-z]:\\")

        schema = json.loads(
            (ROOT / "profiles" / "schemas" / "model.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("workflow_template_id", schema["properties"])
        self.assertIn("workflow_template_version", schema["properties"])


if __name__ == "__main__":
    unittest.main()
