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

from local_gpu_imagegen.engine import AssetRunEngine  # noqa: E402
from local_gpu_imagegen.errors import AssetEngineError  # noqa: E402
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
from local_gpu_imagegen.two_stage_layout import (  # noqa: E402
    TWO_STAGE_LAYOUT_MODE,
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
    derive_subject_seed,
)
from local_gpu_imagegen.workflow_templates import WorkflowTemplateRegistry  # noqa: E402


WIDTH = 1280
HEIGHT = 720
ENDPOINT = "endpoint:two-stage-vertical-slice"
BACKEND_MODEL_ID = "sd_xl_base_1.0.safetensors"
BASE_SEED = 2026072303
PLAN_FIELDS = {
    "profile", "style", "intent", "positive_prompt", "negative_prompt",
    "constraints", "parameters", "max_rounds", "upscale_policy",
    "authorization_scope", "route_token", "model_choice", "backend",
    "endpoint_identity", "model_identity_token", "identity_strength",
    "workflow_template_id", "workflow_template_version",
    "prompt_compiler_id", "prompt_compiler_version",
}


def _layout() -> dict[str, object]:
    return {
        "mode": TWO_STAGE_LAYOUT_MODE,
        "canvas": {"width": WIDTH, "height": HEIGHT},
        "copy_protected_rect": {"x": 0, "y": 0, "width": 576, "height": HEIGHT},
        "subject_mask_rect": {"x": 720, "y": 24, "width": 512, "height": 672},
        "feather_pixels": 32,
        "vae_grow_mask_by": 8,
    }


def _conditioning() -> dict[str, object]:
    return {
        "subject_prompt": "one complete brass telescope on a tripod",
        "subject_negative_prompt": "cropped telescope, duplicate telescope, text",
        "subject_denoise": 0.9,
    }


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _write_rgb_png(path: Path, width: int, height: int, pixel_at: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    callback = pixel_at
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(callback(x, y))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _chunk(b"IEND", b"")
    )


def _float32(value: float) -> float:
    return struct.unpack("=f", struct.pack("=f", value))[0]


def _mask_intensity(x: int, y: int, layout: dict[str, object]) -> int:
    subject = layout["subject_mask_rect"]
    assert isinstance(subject, dict)
    if not (
        subject["x"] <= x < subject["x"] + subject["width"]
        and subject["y"] <= y < subject["y"] + subject["height"]
    ):
        return 0
    local_x = x - subject["x"]
    local_y = y - subject["y"]
    width = subject["width"]
    height = subject["height"]
    feather = layout["feather_pixels"]
    assert isinstance(feather, int)
    value = 1.0
    for distance in (
        local_x,
        width - 1 - local_x,
        local_y,
        height - 1 - local_y,
    ):
        if distance < feather:
            rate = _float32((distance + 1) / feather)
            value = _float32(value * rate)
    return int(_float32(255.0 * value))


class FakeTrustRegistry:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records
        self.observations: list[tuple[str, str, str, str]] = []

    def list_records(self) -> list[dict[str, object]]:
        return copy.deepcopy(self.records)

    def record_observation(
        self,
        catalog_id: str,
        identity: str,
        operation: str,
        run_id: str,
    ) -> None:
        self.observations.append((catalog_id, identity, operation, run_id))


class DeterministicTwoStageBackend:
    def __init__(self, *, mutate_protected_pixel: bool = False) -> None:
        self.mutate_protected_pixel = mutate_protected_pixel
        self.calls: list[dict[str, object]] = []

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(copy.deepcopy(request))
        output_paths = request["output_paths"]
        layout = request["two_stage_layout"]
        model = request["model"]
        workflow = request["workflow"]
        assert isinstance(output_paths, dict)
        assert isinstance(layout, dict)
        assert isinstance(model, dict)
        assert isinstance(workflow, dict)
        base_path = Path(str(output_paths["base"]))
        mask_path = Path(str(output_paths["mask"]))
        final_path = Path(str(output_paths["final"]))
        base_pixel = b"\x18\x30\x48"
        subject_pixel = b"\x80\xa0\xc0"

        _write_rgb_png(base_path, WIDTH, HEIGHT, lambda _x, _y: base_pixel)
        _write_rgb_png(
            mask_path,
            WIDTH,
            HEIGHT,
            lambda x, y: bytes((_mask_intensity(x, y, layout),)) * 3,
        )

        def final_pixel(x: int, y: int) -> bytes:
            if self.mutate_protected_pixel and (x, y) == (0, 0):
                return b"\x19\x30\x48"
            return subject_pixel if _mask_intensity(x, y, layout) > 0 else base_pixel

        _write_rgb_png(final_path, WIDTH, HEIGHT, final_pixel)
        return {
            "ok": True,
            "path": str(final_path),
            "backend": "comfyui",
            "mode": request["mode"],
            "seed": request["seed"],
            "width": WIDTH,
            "height": HEIGHT,
            "model": model["backend_model_id"],
            "endpoint_identity": model["endpoint_identity"],
            "model_identity_token": model["identity_token"],
            "identity_strength": model["identity_strength"],
            "workflow_template_id": workflow["template_id"],
            "workflow_template_version": workflow["template_version"],
            "workflow_job_id": "job:deterministic-two-stage",
            "prompt_compiler_id": request["prompt_compiler_id"],
            "prompt_compiler_version": request["prompt_compiler_version"],
            "stage_outputs": {
                "base": {"path": str(base_path)},
                "final": {"path": str(final_path)},
            },
            "mask_output": {"path": str(mask_path)},
            "subject_seed": request["subject_seed"],
            "control_sha256": workflow["control_sha256"],
            "component_bundle_sha256": request["component_bundle_sha256"],
        }


def _build_stack(
    root: Path,
    *,
    mutate_protected_pixel: bool = False,
) -> tuple[AssetRunEngine, ModelCatalog, CapabilityRouter, DeterministicTwoStageBackend, list[str]]:
    workflows = WorkflowTemplateRegistry(ROOT / "workflows" / "comfyui", root / "workflow-state")
    parameters = {
        "positive_prompt": "catalog validation",
        "negative_prompt": "",
        "seed": 0,
        "steps": 30,
        "guidance_scale": 7.0,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "width": WIDTH,
        "height": HEIGHT,
    }
    standard_workflow = workflows.inspect_shipped(
        "sdxl-txt2img", BACKEND_MODEL_ID, "txt2img", parameters
    )
    two_stage_workflow = workflows.inspect_shipped(
        TWO_STAGE_TEMPLATE_ID, BACKEND_MODEL_ID, "txt2img", parameters
    )
    filesystem = validate_discovery_record({
        "backend": "filesystem",
        "endpoint_identity": "filesystem:two-stage-vertical-slice",
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
        two_stage: bool,
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
                "resolution": {"width": WIDTH, "height": HEIGHT},
                "steps": 30,
                "guidance": 7.0,
                "sampler": "dpmpp_2m",
                "scheduler": "karras",
            },
        }
        binding = {
            "backend": "comfyui",
            "backend_model_id": BACKEND_MODEL_ID,
            "endpoint_identity": ENDPOINT,
            "backend_identity_token": comfyui["identity_token"],
            "template_id": workflow["template_id"],
            "template_version": workflow["template_version"],
            "workflow_sha256": workflow["workflow_sha256"],
            "component_bundle_sha256": bundle["bundle_sha256"],
        }
        if two_stage:
            capabilities["two_stage_layout_modes"] = [TWO_STAGE_LAYOUT_MODE]
            binding["control_sha256"] = build_control_identity(
                _layout(), str(workflow["workflow_sha256"]), "base-subject-v1"
            )
        return {
            "catalog_id": catalog_id,
            "identity_token": filesystem["identity_token"],
            "identity_strength": "cryptographic",
            "scope": "private",
            "identity_record": copy.deepcopy(filesystem),
            "capabilities": capabilities,
            "workflow_binding": binding,
            "component_bundle": bundle,
            "preference": 100 if two_stage else 0,
            "limitations": [],
            "evidence": [{"level": "declared"}],
            "approved_at": "2026-07-23T00:00:00Z",
        }

    standard_id = "local:standard-sdxl-fixture"
    two_stage_id = "local:two-stage-sdxl-fixture"
    trust = FakeTrustRegistry([
        trusted_variant(standard_id, standard_workflow, two_stage=False),
        trusted_variant(two_stage_id, two_stage_workflow, two_stage=True),
    ])
    readiness = {"available_backends": ["comfyui"]}
    models_root = root / "models"
    models_root.mkdir()
    catalog = ModelCatalog(
        models_root,
        lambda: [filesystem, comfyui],
        trust,
        lambda: readiness,
        workflows,
    )
    capability_calls: list[str] = []

    def live_capability(mode: str) -> dict[str, object]:
        capability_calls.append(mode)
        return {
            "mode": mode,
            "available": True,
            "endpoint_identity": ENDPOINT,
            "reason": None,
        }

    router = CapabilityRouter(
        catalog,
        PromptCompilerRegistry(),
        layout_capability_provider=live_capability,
        clock=lambda: 1000.0,
    )
    backend = DeterministicTwoStageBackend(
        mutate_protected_pixel=mutate_protected_pixel
    )
    engine = AssetRunEngine(
        ProfileRegistry(ROOT / "profiles"),
        RunStore(root / "outputs"),
        backend,
        lambda: readiness,
        catalog=catalog,
        router=router,
        compilers=PromptCompilerRegistry(),
        workflows=workflows,
    )
    return engine, catalog, router, backend, capability_calls


def _recommend(router: CapabilityRouter) -> dict[str, object]:
    recommendation = router.recommend({
        "authorization_scope": "private",
        "operation": "txt2img",
        "profile": "ui-visual-asset",
        "style": None,
        "width": WIDTH,
        "height": HEIGHT,
        "affinity_tags": ["illustration", "ui-visual"],
        "required_vram_gb": 12,
        "preferred_model_id": "local:two-stage-sdxl-fixture",
        "two_stage_layout": _layout(),
    })
    assert len(recommendation["routes"]) == 1
    return recommendation["routes"][0]


def _semantic_fidelity() -> dict[str, object]:
    return {
        "required": True,
        "requested_medium": "decorative software product hero asset",
        "required_anchors": [
            "brass telescope hero object on the right",
            "protected left copy-safe area",
        ],
        "forbidden_substitutions": ["paper-only planning workspace"],
    }


def _start(engine: AssetRunEngine, route: dict[str, object]) -> str:
    started = engine.start_run({
        "intent": "Telescope hero with protected left copy space",
        "profile": "ui-visual-asset",
        "subtype": "hero",
        "style": None,
        "constraints": {
            "width": WIDTH,
            "height": HEIGHT,
            "two_stage_layout": _layout(),
            "semantic_fidelity": _semantic_fidelity(),
        },
        "initial_two_stage_conditioning": _conditioning(),
        "model_choice": route["model_id"],
        "backend": "comfyui",
        "authorization_scope": "private",
        "route_token": route["route_token"],
        "max_rounds": 1,
        "upscale_policy": "off",
    })
    return str(started["run_id"])


def _plan(route: dict[str, object]) -> dict[str, object]:
    return {
        "profile": "ui-visual-asset",
        "style": None,
        "intent": "Telescope hero with protected left copy space",
        "positive_prompt": "quiet empty observatory interior with dark left copy space",
        "negative_prompt": "text, watermark, telescope, tripod",
        "constraints": {
            "width": WIDTH,
            "height": HEIGHT,
            "two_stage_layout": _layout(),
            "semantic_fidelity": _semantic_fidelity(),
        },
        "parameters": {"two_stage_conditioning": _conditioning()},
        "max_rounds": 1,
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


def _passing_review(manifest: dict[str, object]) -> dict[str, object]:
    request = manifest["request"]
    assert isinstance(request, dict)
    merged = request["merged_profile"]
    constraints = request["constraints"]
    assert isinstance(merged, dict) and isinstance(constraints, dict)
    rubric = merged["rubric"]
    assert isinstance(rubric, dict)
    not_applicable = {"status": "not_applicable", "observation": "No human is present."}
    constraint_results = {
        name: {"status": "pass", "observation": f"{name} matches the confirmed request."}
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
        "hard_failures": [],
        "critique": "Both stages and the machine pixel report pass the confirmed contract.",
        "constraint_results": constraint_results,
        "visual_checks": {
            "full_resolution_inspected": True,
            "prominent_human": False,
            "limb_separation": copy.deepcopy(not_applicable),
            "feet_and_contact": copy.deepcopy(not_applicable),
            "hands_and_held_objects": copy.deepcopy(not_applicable),
            "text_and_watermarks": {
                "status": "pass",
                "observation": "No baked text or watermark is present.",
            },
        },
        "stage_checks": {
            "base_copy_space": {"status": "pass", "observation": "The base copy space is usable."},
            "base_subject_absent": {"status": "pass", "observation": "The base has no telescope."},
            "final_subject_inside_mask": {"status": "pass", "observation": "The subject stays in-mask."},
            "final_safe_margins": {"status": "pass", "observation": "Final margins are intact."},
            "final_forbidden_content": {"status": "pass", "observation": "Forbidden content is absent."},
            "feather_transition": {"status": "pass", "observation": "The feather is coherent."},
            "pixel_preservation": {"status": "pass", "observation": "The report has zero mismatches."},
        },
        "next_action": "finalize",
    }


class TwoStageVerticalSliceTests(unittest.TestCase):
    def test_catalog_to_review_lifecycle_exposes_only_the_final_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, catalog, router, backend, capability_calls = _build_stack(root)
            catalog_models = catalog.list_models("private")
            self.assertEqual(
                {model["id"] for model in catalog_models},
                {"local:standard-sdxl-fixture", "local:two-stage-sdxl-fixture"},
            )

            route = _recommend(router)
            self.assertEqual(capability_calls, [TWO_STAGE_LAYOUT_MODE])
            self.assertEqual(route["model_id"], "local:two-stage-sdxl-fixture")
            self.assertEqual(route["workflow_template_id"], TWO_STAGE_TEMPLATE_ID)
            self.assertRegex(str(route["component_bundle_sha256"]), r"^[0-9a-f]{64}$")
            self.assertRegex(str(route["control_sha256"]), r"^[0-9a-f]{64}$")

            run_id = _start(engine, route)
            plan = _plan(route)
            self.assertEqual(set(plan), PLAN_FIELDS)
            self.assertNotIn("telescope", str(plan["positive_prompt"]).lower())
            generated, _ = engine.generate_round({
                "run_id": run_id,
                "idempotency_key": "two-stage-vertical-initial",
                "action": "initial",
                "edit_mode": "txt2img",
                "seed": BASE_SEED,
                "change_summary": "Generate the confirmed base and subject stages.",
                "plan": plan,
            })

            self.assertEqual(generated["state"], "generated")
            manifest = engine.get_run({"run_id": run_id})
            round_value = manifest["rounds"][0]
            self.assertEqual([stage["role"] for stage in round_value["stages"]], ["base", "subject"])
            self.assertEqual(round_value["stage_units"], 2)
            self.assertEqual(
                round_value["backend_result"]["subject_seed"],
                derive_subject_seed(BASE_SEED),
            )
            self.assertEqual(round_value["pixel_preservation"]["mismatched_pixels"], 0)
            self.assertEqual(round_value["pixel_preservation"]["copy_mismatched_pixels"], 0)
            self.assertEqual(
                round_value["mask_artifact"]["soft_mask_validation"]["outside_nonzero_pixels"],
                0,
            )
            self.assertEqual(manifest["stage_budget"], {"maximum": 2, "consumed": 2})
            self.assertEqual(manifest["request"]["max_rounds"], 1)
            self.assertEqual(len(manifest["rounds"]), 1)
            self.assertEqual(len(backend.calls), 1)

            reviewed = engine.record_review({
                "run_id": run_id,
                "round_number": 1,
                "review": _passing_review(manifest),
            })
            candidate = reviewed["finalization_candidate"]
            base_hash = round_value["stages"][0]["image"]["sha256"]
            mask_hash = round_value["mask_artifact"]["sha256"]
            final_hash = round_value["image"]["sha256"]
            self.assertEqual(candidate["image_sha256"], final_hash)
            self.assertNotIn(candidate["image_sha256"], {base_hash, mask_hash})
            self.assertEqual(candidate["confirmation"], f"finalize:{run_id}:1:{final_hash}")

    def test_one_protected_pixel_mutation_stops_partial_without_a_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine, _catalog, router, backend, _capability_calls = _build_stack(
                root,
                mutate_protected_pixel=True,
            )
            route = _recommend(router)
            run_id = _start(engine, route)

            with self.assertRaisesRegex(AssetEngineError, "two_stage_pixel_mismatch"):
                engine.generate_round({
                    "run_id": run_id,
                    "idempotency_key": "two-stage-protected-mutation",
                    "action": "initial",
                    "edit_mode": "txt2img",
                    "seed": BASE_SEED,
                    "change_summary": "Exercise the protected-pixel failure gate.",
                    "plan": _plan(route),
                })

            manifest = engine.get_run({"run_id": run_id})
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(manifest["state"], "partial")
            self.assertEqual(manifest["stage_budget"], {"maximum": 2, "consumed": 2})
            self.assertEqual(manifest["request"]["max_rounds"], 1)
            self.assertEqual(manifest["rounds"], [])
            self.assertEqual(
                [stage["role"] for stage in manifest["attempts"][0]["retained_stages"]],
                ["base", "subject"],
            )
            self.assertNotIn("finalization_candidate", manifest)


if __name__ == "__main__":
    unittest.main()
