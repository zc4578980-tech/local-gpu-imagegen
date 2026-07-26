from __future__ import annotations

import copy
import hashlib
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.engine import AssetRunEngine, recoverable_next_actions  # noqa: E402
from local_gpu_imagegen.model_catalog import ModelCatalog  # noqa: E402
from local_gpu_imagegen.model_identity import (  # noqa: E402
    build_component_bundle,
    identity_token,
    validate_discovery_record,
)
from local_gpu_imagegen.model_router import CapabilityRouter  # noqa: E402
from local_gpu_imagegen.profile_registry import ProfileRegistry  # noqa: E402
from local_gpu_imagegen.prompt_compilers import PromptCompilerRegistry  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402
from local_gpu_imagegen.workflow_templates import WorkflowTemplateRegistry  # noqa: E402


ENDPOINT = "endpoint:regional-test"
BACKEND_MODEL_ID = "sd_xl_base_1.0.safetensors"


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _write_png(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x20\x40\x80" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )


class FakeTrustRegistry:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    def list_records(self) -> list[dict[str, object]]:
        return copy.deepcopy(self.records)

    def record_observation(
        self,
        catalog_id: str,
        identity: str,
        operation: str,
        run_id: str,
    ) -> None:
        record = next(
            item
            for item in self.records
            if item["catalog_id"] == catalog_id and item["identity_token"] == identity
        )
        observation = {"level": "observed", "operation": operation, "run_id": run_id}
        if observation not in record["evidence"]:
            record["evidence"].append(observation)


class DeterministicComfyBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(copy.deepcopy(request))
        output_path = Path(str(request["output_path"]))
        _write_png(output_path, int(request["width"]), int(request["height"]))
        model = request["model"]
        workflow = request["workflow"]
        assert isinstance(model, dict) and isinstance(workflow, dict)
        return {
            "ok": True,
            "path": str(output_path),
            "backend": "comfyui",
            "mode": request["mode"],
            "seed": request["seed"],
            "width": request["width"],
            "height": request["height"],
            "model": model["backend_model_id"],
            "endpoint_identity": model["endpoint_identity"],
            "model_identity_token": model["identity_token"],
            "identity_strength": model["identity_strength"],
            "workflow_template_id": workflow["template_id"],
            "workflow_template_version": workflow["template_version"],
            "workflow_job_id": f"job:regional-{len(self.calls)}",
            "prompt_compiler_id": request["prompt_compiler_id"],
            "prompt_compiler_version": request["prompt_compiler_version"],
        }


def _layout() -> dict[str, object]:
    return {
        "mode": "copy-subject-v1",
        "copy_region": {"x": 0.0, "y": 0.0, "width": 0.45, "height": 1.0},
        "subject_region": {"x": 0.68, "y": 0.0, "width": 0.30, "height": 1.0},
    }


def _conditioning() -> dict[str, object]:
    return {
        "copy_prompt": "quiet dark-blue copy space for a product headline",
        "copy_strength": 1.15,
        "subject_prompt": "a brass telescope hero object on the right",
        "subject_strength": 1.25,
    }


def _semantic_fidelity() -> dict[str, object]:
    return {
        "required": True,
        "requested_medium": "decorative software product hero asset",
        "required_anchors": [
            "brass telescope hero object on the right",
            "left copy-safe area",
        ],
        "forbidden_substitutions": ["paper-only planning workspace"],
    }


def _review(request: dict[str, object]) -> dict[str, object]:
    merged = request["merged_profile"]
    constraints = request["constraints"]
    assert isinstance(merged, dict) and isinstance(constraints, dict)
    rubric = merged["rubric"]
    assert isinstance(rubric, dict)
    constraint_results = {
        name: {
            "status": "fail" if name == "regional_layout" else "pass",
            "observation": (
                "The copy/subject relation was violated."
                if name == "regional_layout"
                else f"{name} matches the confirmed request."
            ),
        }
        for name in constraints
    }
    semantic = constraints["semantic_fidelity"]
    constraint_results["semantic_fidelity"] = {
        "status": "pass",
        "observation": "The telescope hero remains a composable software asset.",
        "anchor_results": [
            {
                "anchor": anchor,
                "status": "pass",
                "observation": "The required hero anchor is retained.",
            }
            for anchor in semantic["required_anchors"]
        ],
        "substitution_results": [
            {
                "substitution": substitution,
                "status": "absent",
                "observation": "The forbidden replacement is absent.",
            }
            for substitution in semantic["forbidden_substitutions"]
        ],
    }
    return {
        "scores": {name: 4 for name in rubric},
        "hard_failures": ["explicit_constraint_violation"],
        "critique": "The subject entered the confirmed copy-safe region.",
        "constraint_results": constraint_results,
        "visual_checks": {
            "full_resolution_inspected": True,
            "prominent_human": False,
            "limb_separation": {"status": "not_applicable", "observation": "No human is present."},
            "feet_and_contact": {"status": "not_applicable", "observation": "No human is present."},
            "hands_and_held_objects": {"status": "not_applicable", "observation": "No human is present."},
            "text_and_watermarks": {"status": "pass", "observation": "No baked text or watermark is visible."},
        },
        "next_action": "refine",
    }


class RegionalVerticalSliceTests(unittest.TestCase):
    def test_public_regional_route_retains_conditioning_across_exhausted_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            workflows = WorkflowTemplateRegistry(
                ROOT / "workflows" / "comfyui",
                temporary_root / "workflow-state",
            )
            catalog_parameters = {
                "positive_prompt": "catalog validation",
                "negative_prompt": "",
                "seed": 0,
                "steps": 30,
                "guidance_scale": 7.0,
                "sampler": "dpmpp_2m",
                "scheduler": "karras",
                "width": 1024,
                "height": 1024,
            }
            standard_workflow = workflows.inspect_shipped(
                "sdxl-txt2img", BACKEND_MODEL_ID, "txt2img", catalog_parameters
            )
            regional_workflow = workflows.inspect_shipped(
                "sdxl-regional-txt2img", BACKEND_MODEL_ID, "txt2img", catalog_parameters
            )
            filesystem = validate_discovery_record({
                "backend": "filesystem",
                "endpoint_identity": "filesystem:regional-test",
                "backend_model_id": BACKEND_MODEL_ID,
                "format": ".safetensors",
                "byte_size": 2048,
                "modified_ns": 123,
                "sha256": "a" * 64,
                "identity_strength": "cryptographic",
                "metadata": {},
            })
            filesystem["identity_token"] = identity_token(filesystem)
            comfyui = validate_discovery_record({
                "backend": "comfyui",
                "endpoint_identity": ENDPOINT,
                "backend_model_id": BACKEND_MODEL_ID,
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
            comfyui["identity_token"] = identity_token(comfyui)

            component = {
                "role": "primary_model",
                "loader_class": "CheckpointLoaderSimple",
                "loader_input": "ckpt_name",
                "backend_model_id": BACKEND_MODEL_ID,
                "filesystem_identity_token": filesystem["identity_token"],
                "sha256": filesystem["sha256"],
                "byte_size": filesystem["byte_size"],
            }

            def trusted_variant(
                catalog_id: str,
                workflow: dict[str, object],
                *,
                regional: bool,
            ) -> dict[str, object]:
                bundle = build_component_bundle([component], {
                    "template_id": workflow["template_id"],
                    "template_version": workflow["template_version"],
                    "sha256": workflow["workflow_sha256"],
                })
                capabilities: dict[str, object] = {
                    "model_family": "sdxl",
                    "prompt_dialect": "natural-v1",
                    "operations": ["txt2img"],
                    "minimum_dimension": 512,
                    "maximum_dimension": 1536,
                    "minimum_vram_gb": 10,
                    "negative_prompt": "supported",
                    "affinity": ["illustration", "ui-visual"],
                    "recommended": {
                        "resolution": {"width": 1024, "height": 1024},
                        "steps": 30,
                        "guidance": 7.0,
                        "sampler": "dpmpp_2m",
                        "scheduler": "karras",
                    },
                }
                if regional:
                    capabilities["regional_layout_modes"] = ["copy-subject-v1"]
                return {
                    "catalog_id": catalog_id,
                    "identity_token": filesystem["identity_token"],
                    "identity_strength": "cryptographic",
                    "scope": "public_candidate",
                    "identity_record": copy.deepcopy(filesystem),
                    "capabilities": capabilities,
                    "workflow_binding": {
                        "backend": "comfyui",
                        "backend_model_id": BACKEND_MODEL_ID,
                        "endpoint_identity": ENDPOINT,
                        "backend_identity_token": comfyui["identity_token"],
                        "template_id": workflow["template_id"],
                        "template_version": workflow["template_version"],
                        "workflow_sha256": workflow["workflow_sha256"],
                        "component_bundle_sha256": bundle["bundle_sha256"],
                    },
                    "component_bundle": bundle,
                    "preference": 100 if regional else 0,
                    "public_metadata": {
                        "source": "https://example.invalid/sdxl",
                        "license_id": "test-license",
                        "license_url": "https://example.invalid/license",
                        "output_redistribution_status": "approved",
                        "components": [{
                            "role": "primary_model",
                            "sha256": filesystem["sha256"],
                            "source": "https://example.invalid/sdxl-file",
                            "license_id": "test-license",
                            "license_url": "https://example.invalid/license",
                            "output_redistribution_status": "approved",
                        }],
                    },
                    "limitations": [],
                    "evidence": [{"level": "declared"}],
                    "approved_at": "2026-07-23T00:00:00Z",
                }

            legacy_id = "local:" + str(filesystem["identity_token"]).removeprefix("model:")[:24]
            regional_bundle = build_component_bundle([component], {
                "template_id": regional_workflow["template_id"],
                "template_version": regional_workflow["template_version"],
                "sha256": regional_workflow["workflow_sha256"],
            })
            regional_id = "local:" + hashlib.sha256(
                f"{filesystem['identity_token']}\n{regional_bundle['bundle_sha256']}".encode("utf-8")
            ).hexdigest()[:24]
            trust = FakeTrustRegistry([
                trusted_variant(legacy_id, standard_workflow, regional=False),
                trusted_variant(regional_id, regional_workflow, regional=True),
            ])
            models_root = temporary_root / "models"
            models_root.mkdir()
            readiness = {"available_backends": ["comfyui"]}
            catalog = ModelCatalog(
                models_root,
                lambda: [filesystem, comfyui],
                trust,
                lambda: readiness,
                workflows,
            )
            router = CapabilityRouter(
                catalog,
                PromptCompilerRegistry(),
                regional_capability_provider=lambda mode: {
                    "mode": mode,
                    "available": True,
                    "endpoint_identity": ENDPOINT,
                    "reason": None,
                },
                clock=lambda: 1000.0,
            )
            backend = DeterministicComfyBackend()
            engine = AssetRunEngine(
                ProfileRegistry(ROOT / "profiles"),
                RunStore(temporary_root / "outputs"),
                backend,
                lambda: readiness,
                catalog=catalog,
                router=router,
                compilers=PromptCompilerRegistry(),
                workflows=workflows,
            )

            layout = _layout()
            initial_conditioning = _conditioning()
            requirements = {
                "authorization_scope": "public_evidence",
                "operation": "txt2img",
                "profile": "ui-visual-asset",
                "style": None,
                "width": 1280,
                "height": 720,
                "affinity_tags": ["illustration", "ui-visual"],
                "required_vram_gb": 12,
                "preferred_model_id": regional_id,
                "regional_layout": layout,
            }
            recommendation = router.recommend(requirements)
            self.assertEqual([route["model_id"] for route in recommendation["routes"]], [regional_id])
            route = recommendation["routes"][0]
            started = engine.start_run({
                "intent": "Telescope hero with left copy space",
                "profile": "ui-visual-asset",
                "subtype": "hero",
                "style": None,
                "constraints": {
                    "width": 1280,
                    "height": 720,
                    "regional_layout": layout,
                    "semantic_fidelity": _semantic_fidelity(),
                },
                "initial_regional_conditioning": initial_conditioning,
                "model_choice": regional_id,
                "backend": "comfyui",
                "authorization_scope": "public_evidence",
                "route_token": route["route_token"],
                "max_rounds": 2,
                "upscale_policy": "off",
            })

            def plan(conditioning: dict[str, object]) -> dict[str, object]:
                return {
                    "profile": "ui-visual-asset",
                    "style": None,
                    "intent": "Telescope hero with left copy space",
                    "positive_prompt": "A brass telescope hero object with quiet copy space",
                    "negative_prompt": "baked text, watermark",
                    "constraints": {
                        "width": 1280,
                        "height": 720,
                        "regional_layout": layout,
                        "semantic_fidelity": _semantic_fidelity(),
                    },
                    "parameters": {"regional_conditioning": conditioning},
                    "max_rounds": 2,
                    "upscale_policy": "off",
                    "authorization_scope": route["authorization_scope"],
                    "route_token": route["route_token"],
                    "model_choice": route["model_id"],
                    "backend": route["backend"],
                    "endpoint_identity": route["endpoint_identity"],
                    "model_identity_token": route["identity_token"],
                    "identity_strength": route["identity_strength"],
                    "workflow_template_id": route["workflow_template_id"],
                    "workflow_template_version": route["workflow_template_version"],
                    "prompt_compiler_id": route["prompt_compiler_id"],
                    "prompt_compiler_version": route["prompt_compiler_version"],
                }

            run_id = str(started["run_id"])
            engine.generate_round({
                "run_id": run_id,
                "idempotency_key": "regional-initial-1",
                "action": "initial",
                "edit_mode": "txt2img",
                "seed": 42,
                "change_summary": "Initial confirmed regional layout.",
                "plan": plan(initial_conditioning),
            })
            first = engine.get_run({"run_id": run_id})
            engine.record_review({"run_id": run_id, "round_number": 1, "review": _review(first["request"])})

            refined_conditioning = copy.deepcopy(initial_conditioning)
            refined_conditioning["subject_strength"] = 1.4
            engine.generate_round({
                "run_id": run_id,
                "idempotency_key": "regional-refine-2",
                "action": "refine",
                "edit_mode": "txt2img",
                "seed": 42,
                "change_summary": "Preserve geometry. Change subject strength.",
                "plan": plan(refined_conditioning),
            })
            second = engine.get_run({"run_id": run_id})
            engine.record_review({"run_id": run_id, "round_number": 2, "review": _review(second["request"])})

            manifest = engine.get_run({"run_id": run_id})
            self.assertEqual(manifest["request"]["constraints"]["regional_layout"], layout)
            self.assertEqual(manifest["request"]["initial_regional_conditioning"], initial_conditioning)
            self.assertNotEqual(manifest["attempts"][0]["request_hash"], manifest["attempts"][1]["request_hash"])
            self.assertEqual(
                manifest["attempts"][1]["generation_plan"]["parameters"]["regional_conditioning"]["subject_strength"],
                1.4,
            )
            self.assertEqual(manifest["state"], "reviewed")
            self.assertEqual(recoverable_next_actions(manifest), ["get_run"])
            self.assertNotIn("finalization_candidate", manifest)
            self.assertEqual(len(backend.calls), 2)


if __name__ == "__main__":
    unittest.main()
