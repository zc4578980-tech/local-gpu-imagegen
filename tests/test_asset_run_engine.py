from __future__ import annotations

import json
import base64
import copy
import hashlib
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import zlib
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.engine import AssetRunEngine  # noqa: E402
import local_gpu_imagegen.engine as engine_module  # noqa: E402
from local_gpu_imagegen.artifacts import validate_png  # noqa: E402
from local_gpu_imagegen.errors import AssetEngineError, ConflictError, StateError, ValidationError  # noqa: E402
from local_gpu_imagegen.preview import MAX_PREVIEW_BYTES, PreviewResult  # noqa: E402
from local_gpu_imagegen.profile_registry import ProfileRegistry  # noqa: E402
from local_gpu_imagegen.prompt_compilers import PromptCompilerRegistry  # noqa: E402
from local_gpu_imagegen.regional_layout import REGIONAL_TEMPLATE_ID  # noqa: E402
from local_gpu_imagegen.run_store import RunStore  # noqa: E402
from local_gpu_imagegen.two_stage_layout import (  # noqa: E402
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
    derive_subject_seed,
)
from local_gpu_imagegen.workflow_templates import WorkflowTemplateRegistry  # noqa: E402


TEST_MODEL_ID = "test/approved-anime"
TEST_ENDPOINT = "endpoint:test"
TEST_IDENTITY = "model:" + "a" * 64


def visual_checks(*, limb_status: str = "pass") -> dict[str, object]:
    return {
        "full_resolution_inspected": True,
        "prominent_human": True,
        "limb_separation": {
            "status": limb_status,
            "observation": "Both leg silhouettes were inspected at full resolution.",
        },
        "feet_and_contact": {
            "status": "pass",
            "observation": "Both feet and contact points are distinct.",
        },
        "hands_and_held_objects": {
            "status": "pass",
            "observation": "Both hands are distinct from held objects.",
        },
        "text_and_watermarks": {
            "status": "pass",
            "observation": "No text or watermark is visible.",
        },
    }


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF)


def write_test_png(
    path: Path,
    width: int = 256,
    height: int = 256,
    pixel: bytes = b"\x20\x40\x80",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + pixel * width for _ in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(scanlines)) + _chunk(b"IEND", b""))


def write_test_pixels(
    path: Path,
    width: int,
    height: int,
    pixel_at: Callable[[int, int], bytes],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(
        b"\x00" + b"".join(pixel_at(x, y) for x in range(width))
        for y in range(height)
    )
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(scanlines))
        + _chunk(b"IEND", b"")
    )


class FakeBackendRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.exit_code = 0
        self.stderr = ""
        self.path_override: Path | None = None
        self.result_overrides: dict[str, object] = {}

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(copy.deepcopy(request))
        if self.exit_code != 0:
            raise AssetEngineError(
                "backend_command_failed",
                "Image backend command failed.",
                "backend",
                {"exit_code": self.exit_code, "stderr": self.stderr},
            )
        output_path = Path(str(request["output_path"]))
        write_test_png(output_path, int(request["width"]), int(request["height"]))
        model = request["model"]
        assert isinstance(model, dict)
        result = {
            "ok": True,
            "path": str(self.path_override or output_path),
            "backend": request["backend"],
            "mode": request["mode"],
            "seed": request["seed"],
            "width": request["width"],
            "height": request["height"],
            "model": model["backend_model_id"],
            "endpoint_identity": model["endpoint_identity"],
            "model_identity_token": model["identity_token"],
            "identity_strength": model["identity_strength"],
            "workflow_template_id": None,
            "workflow_template_version": None,
            "prompt_compiler_id": request["prompt_compiler_id"],
            "prompt_compiler_version": request["prompt_compiler_version"],
        }
        result.update(self.result_overrides)
        return result


class TwoStageBackendRunner:
    def __init__(self, *, failure: str | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.failure = failure

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(copy.deepcopy(request))
        output_paths = request["output_paths"]
        assert isinstance(output_paths, dict)
        width = int(request["width"])
        height = int(request["height"])
        layout = request["two_stage_layout"]
        assert isinstance(layout, dict)
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        base_path = Path(str(output_paths["base"]))
        mask_path = Path(str(output_paths["mask"]))
        final_path = Path(str(output_paths["final"]))
        write_test_png(base_path, width, height)
        if self.failure == "malformed_base":
            base_path.write_bytes(b"malformed base")
            raise AssetEngineError("backend_stage_failed", "Subject stage failed.", "backend")
        if self.failure == "base_only":
            raise AssetEngineError("backend_stage_failed", "Subject stage failed.", "backend")
        if self.failure == "malformed_final":
            final_path.write_bytes(b"malformed final")
            raise AssetEngineError("backend_stage_failed", "Subject stage failed.", "backend")

        def mask_pixel(x: int, y: int) -> bytes:
            inside = (
                subject["x"] <= x < subject["x"] + subject["width"]
                and subject["y"] <= y < subject["y"] + subject["height"]
            )
            if self.failure == "mask_leak" and (x, y) == (0, 0):
                inside = True
            return b"\xff\xff\xff" if inside else b"\x00\x00\x00"

        write_test_pixels(mask_path, width, height, mask_pixel)

        def final_pixel(x: int, y: int) -> bytes:
            if self.failure == "protected_change" and (x, y) == (0, 0):
                return b"\x21\x40\x80"
            return b"\x20\x40\x80"

        write_test_pixels(final_path, width, height, final_pixel)
        model = request["model"]
        workflow = request["workflow"]
        assert isinstance(model, dict) and isinstance(workflow, dict)
        return {
            "ok": True,
            "path": str(final_path),
            "backend": request["backend"],
            "mode": request["mode"],
            "seed": request["seed"],
            "width": width,
            "height": height,
            "model": model["backend_model_id"],
            "endpoint_identity": model["endpoint_identity"],
            "model_identity_token": model["identity_token"],
            "identity_strength": model["identity_strength"],
            "workflow_template_id": workflow["template_id"],
            "workflow_template_version": workflow["template_version"],
            "workflow_job_id": "job:two-stage-test",
            "prompt_compiler_id": request["prompt_compiler_id"],
            "prompt_compiler_version": request["prompt_compiler_version"],
            "stage_outputs": {
                "base": {"path": str(base_path)},
                "final": {"path": str(final_path)},
            },
            "mask_output": {"path": str(mask_path)},
            "subject_seed": derive_subject_seed(request["seed"]),
            "control_sha256": workflow["control_sha256"],
            "component_bundle_sha256": request["component_bundle_sha256"],
        }


class RecoveringTwoStageBackendRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.delegate = TwoStageBackendRunner()

    def __call__(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(copy.deepcopy(request))
        if "recovery_job_id" not in request:
            callback = request.get("backend_job_callback")
            assert callable(callback)
            callback("job-two-stage-timeout")
            raise StateError(
                "comfyui_job_timed_out",
                "ComfyUI job did not finish within the confirmed timeout.",
                {"job_id": "job-two-stage-timeout", "state": "running"},
            )
        return self.delegate(request)


class FakeCatalog:
    def __init__(self) -> None:
        self.identity_token = TEST_IDENTITY
        self.observations: list[tuple[str, str, str, str]] = []
        self.workflows = None

    def model(self) -> dict[str, object]:
        return {
            "id": TEST_MODEL_ID,
            "source": "test-fixture",
            "license_id": "test-only",
            "license_url": None,
            "license_status": "approved",
            "backend": "webui",
            "endpoint_identity": TEST_ENDPOINT,
            "backend_model_id": "actual-loaded-model",
            "format": ".safetensors",
            "byte_size": 1,
            "modified_ns": 1,
            "sha256": "b" * 64,
            "identity_strength": "cryptographic",
            "metadata": {},
            "identity_token": self.identity_token,
            "public_evidence_eligible": True,
            "recommended": {
                "resolution": {"width": 256, "height": 256},
                "steps": 4,
                "guidance": 6.0,
                "sampler": "Euler a",
                "scheduler": None,
            },
        }

    def list_models(self, scope: str) -> list[dict[str, object]]:
        if scope not in {"private", "public_evidence"}:
            raise ValidationError("invalid_authorization_scope", "Invalid test scope.")
        return [self.model()]

    def resolve(self, model_id: str, scope: str) -> dict[str, object]:
        if model_id != TEST_MODEL_ID or scope not in {"private", "public_evidence"}:
            raise ValidationError("model_not_eligible", "Model is not eligible.")
        return self.model()

    def verify_locked_route(self, route: dict[str, object]) -> dict[str, object]:
        if route.get("identity_token") != self.identity_token:
            raise ConflictError("model_identity_drifted", "Confirmed model identity changed.")
        return self.model()

    def record_observation(self, model_id: str, identity: str, operation: str, run_id: str) -> None:
        self.observations.append((model_id, identity, operation, run_id))

    def drift(self) -> None:
        self.identity_token = "model:" + "c" * 64


class FakeRouter:
    def __init__(self, catalog: FakeCatalog) -> None:
        self.catalog = catalog
        self.routes: dict[str, dict[str, object]] = {}
        self.counter = 0

    def issue(self, arguments: dict[str, object]) -> dict[str, object]:
        self.counter += 1
        token = f"route:test-{self.counter}"
        constraints = arguments["constraints"]
        assert isinstance(constraints, dict)
        route = {
            "requirements": {},
            "route_token": token,
            "expires_at": 9999999999.0,
            "model_id": arguments["model_choice"],
            "authorization_scope": arguments["authorization_scope"],
            "operation": "txt2img",
            "profile": arguments["profile"],
            "style": arguments["style"],
            "width": constraints["width"],
            "height": constraints["height"],
            "backend": arguments["backend"],
            "endpoint_identity": TEST_ENDPOINT,
            "identity_token": self.catalog.identity_token,
            "identity_strength": "cryptographic",
            "sha256": "b" * 64,
            "workflow_template_id": None,
            "workflow_template_version": None,
            "prompt_compiler_id": "sd15-tags-v1",
            "prompt_compiler_version": 1,
        }
        self.routes[token] = route
        return copy.deepcopy(route)

    def confirm(self, route_token: str, model_id: str) -> dict[str, object]:
        route = self.routes.get(route_token)
        if route is None or route["model_id"] != model_id:
            raise ConflictError("route_confirmation_expired", "Route changed or expired.")
        return copy.deepcopy(route)


class FakePostprocessor:
    def __init__(self, models: list[str] | None = None) -> None:
        self.models = list(models or [])
        self.available_calls = 0
        self.available_failure: Exception | None = None
        self.upscale_calls: list[tuple[Path, Path, str]] = []
        self.failure: AssetEngineError | None = None
        self.leave_pending_on_failure = False
        self.mutate_source_on_failure = False
        self.failure_artifact_writer: Callable[[Path, Path], None] | None = None

    def available_models(self) -> list[str]:
        self.available_calls += 1
        if self.available_failure is not None:
            raise self.available_failure
        return list(self.models)

    def upscale(self, source: Path, destination: Path, model: str) -> dict[str, object]:
        source = Path(source).resolve()
        destination = Path(destination).resolve()
        self.upscale_calls.append((source, destination, model))
        if self.failure is not None:
            if self.failure_artifact_writer is not None:
                self.failure_artifact_writer(source, destination)
            if self.mutate_source_on_failure:
                write_test_png(source, 256, 256, b"\x80\x40\x20")
            if self.leave_pending_on_failure:
                (destination.parent / "final-upscaled.pending.png").write_bytes(b"residue")
            raise self.failure
        source_metadata = validate_png(source, 256, 256)
        write_test_png(destination, 1024, 1024)
        output_metadata = validate_png(destination, 1024, 1024)
        source_metadata["path"] = str(source)
        output_metadata["path"] = str(destination)
        return {
            "type": "anime_upscale",
            "model": model,
            "scale": 4,
            "source": source_metadata,
            "output": output_metadata,
        }


class SimulatedCrash(BaseException):
    pass


def create_directory_alias(alias: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(alias))
    else:
        alias.symlink_to(target, target_is_directory=True)


class AssetRunEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temporary_directory.name) / "output"
        profiles_root = Path(self.temporary_directory.name) / "profiles"
        shutil.copytree(ROOT / "profiles", profiles_root)
        model_path = profiles_root / "models" / "sd-turbo.json"
        model = json.loads(model_path.read_text(encoding="utf-8"))
        model.update({
            "id": TEST_MODEL_ID,
            "source": "test-fixture",
            "license_id": "test-only",
            "license_status": "approved",
            "backends": ["webui"],
            "known_local": True,
            "enabled": True,
        })
        model_path.write_text(json.dumps(model), encoding="utf-8")
        self.registry = ProfileRegistry(profiles_root)
        self.runner = FakeBackendRunner()
        self.postprocessor = FakePostprocessor()
        self.catalog = FakeCatalog()
        self.router = FakeRouter(self.catalog)
        self.compilers = PromptCompilerRegistry()
        self.capabilities = {"available_backends": ["webui", "diffusers"], "cuda": True}
        self.engine = AssetRunEngine(
            self.registry,
            RunStore(self.output_root),
            self.runner,
            lambda: self.capabilities,
            self.postprocessor,
            catalog=self.catalog,
            router=self.router,
            compilers=self.compilers,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def start_arguments(
        self,
        *,
        max_rounds: int = 3,
        style: str | None = None,
        upscale_policy: str = "off",
    ) -> dict[str, object]:
        arguments: dict[str, object] = {
            "profile": "standalone-illustration",
            "style": style,
            "intent": "A calm coast at dawn.",
            "constraints": {"width": 256, "height": 256},
            "model_choice": TEST_MODEL_ID,
            "backend": "webui",
            "upscale_policy": upscale_policy,
            "max_rounds": max_rounds,
            "authorization_scope": "private",
        }
        route = self.router.issue(arguments)
        arguments["route_token"] = route["route_token"]
        return arguments

    @staticmethod
    def regional_layout() -> dict[str, object]:
        return {
            "mode": "copy-subject-v1",
            "copy_region": {"x": 0.0, "y": 0.0, "width": 0.4, "height": 1.0},
            "subject_region": {"x": 0.65, "y": 0.0, "width": 0.35, "height": 1.0},
        }

    @staticmethod
    def regional_conditioning() -> dict[str, object]:
        return {
            "copy_prompt": "quiet dark-blue copy space",
            "copy_strength": 1.1,
            "subject_prompt": "a sailor looking over the sea",
            "subject_strength": 1.25,
        }

    def regional_start_arguments(self) -> dict[str, object]:
        layout = self.regional_layout()
        arguments: dict[str, object] = {
            "profile": "standalone-illustration",
            "style": None,
            "intent": "A calm coast at dawn.",
            "constraints": {"width": 256, "height": 256, "regional_layout": layout},
            "initial_regional_conditioning": self.regional_conditioning(),
            "model_choice": TEST_MODEL_ID,
            "backend": "comfyui",
            "upscale_policy": "off",
            "max_rounds": 3,
            "authorization_scope": "private",
        }
        route = self.router.issue(arguments)
        route.update({
            "requirements": {"regional_layout": copy.deepcopy(layout)},
            "workflow_template_id": REGIONAL_TEMPLATE_ID,
            "workflow_template_version": 1,
            "prompt_compiler_id": "natural-v1",
            "prompt_compiler_version": 1,
        })
        self.router.routes[str(route["route_token"])] = copy.deepcopy(route)
        arguments["route_token"] = route["route_token"]
        if "comfyui" not in self.capabilities["available_backends"]:
            self.capabilities["available_backends"].append("comfyui")
        self.engine.workflows = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            Path(self.temporary_directory.name) / "workflow-state",
        )
        self.runner.result_overrides.update({
            "workflow_template_id": REGIONAL_TEMPLATE_ID,
            "workflow_template_version": 1,
            "workflow_job_id": "job:regional-test",
        })
        return arguments

    def regional_plan(
        self,
        route: dict[str, object],
        conditioning: dict[str, object] | None = None,
    ) -> dict[str, object]:
        plan = self.plan(route=route)
        plan["backend"] = "comfyui"
        plan["constraints"]["regional_layout"] = copy.deepcopy(
            route["requirements"]["regional_layout"]
        )
        plan["parameters"] = {
            "regional_conditioning": copy.deepcopy(
                conditioning if conditioning is not None else self.regional_conditioning()
            )
        }
        return plan

    @staticmethod
    def two_stage_layout() -> dict[str, object]:
        return {
            "mode": "copy-subject-two-stage-v1",
            "canvas": {"width": 640, "height": 320},
            "copy_protected_rect": {"x": 0, "y": 0, "width": 224, "height": 320},
            "subject_mask_rect": {"x": 304, "y": 16, "width": 320, "height": 288},
            "feather_pixels": 0,
            "vae_grow_mask_by": 0,
        }

    @staticmethod
    def two_stage_conditioning() -> dict[str, object]:
        return {
            "subject_prompt": "one complete brass telescope on a tripod",
            "subject_negative_prompt": "cropped subject, duplicate telescope",
            "subject_denoise": 0.9,
        }

    def two_stage_start_arguments(self) -> dict[str, object]:
        layout = self.two_stage_layout()
        self.engine.workflows = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            Path(self.temporary_directory.name) / "two-stage-workflow-state",
        )
        inspected = self.engine.workflows.inspect_shipped(
            TWO_STAGE_TEMPLATE_ID,
            "actual-loaded-model",
            "txt2img",
            {
                "positive_prompt": "catalog validation",
                "negative_prompt": "",
                "seed": 0,
                "steps": 4,
                "guidance_scale": 6.0,
                "sampler": "euler",
                "scheduler": "normal",
                "width": 640,
                "height": 320,
            },
        )
        arguments = self.start_arguments(max_rounds=2)
        arguments.update({
            "constraints": {
                "width": 640,
                "height": 320,
                "two_stage_layout": copy.deepcopy(layout),
            },
            "initial_two_stage_conditioning": self.two_stage_conditioning(),
            "backend": "comfyui",
        })
        route = self.router.issue(arguments)
        route.update({
            "requirements": {"two_stage_layout": copy.deepcopy(layout)},
            "workflow_template_id": TWO_STAGE_TEMPLATE_ID,
            "workflow_template_version": 1,
            "prompt_compiler_id": "natural-v1",
            "prompt_compiler_version": 1,
            "control_sha256": build_control_identity(
                layout,
                inspected["workflow_sha256"],
                "base-subject-v1",
            ),
            "component_bundle_sha256": "b" * 64,
        })
        self.router.routes[str(route["route_token"])] = copy.deepcopy(route)
        arguments["route_token"] = route["route_token"]
        if "comfyui" not in self.capabilities["available_backends"]:
            self.capabilities["available_backends"].append("comfyui")
        return arguments

    def two_stage_plan(self, route: dict[str, object]) -> dict[str, object]:
        plan = self.plan(route=route, max_rounds=2, parameters={
            "two_stage_conditioning": self.two_stage_conditioning(),
        })
        plan.update({
            "backend": "comfyui",
            "positive_prompt": "dark quiet observatory background",
            "negative_prompt": "text, watermark, telescope",
        })
        plan["constraints"] = {
            "width": 640,
            "height": 320,
            "two_stage_layout": self.two_stage_layout(),
        }
        return plan

    def execute_two_stage(self, runner: TwoStageBackendRunner) -> tuple[str, object]:
        self.engine.backend_runner = runner
        started = self.engine.start_run(self.two_stage_start_arguments())
        run_id = str(started["run_id"])
        manifest = self.engine.get_run({"run_id": run_id})
        route = manifest["request"]["route"]
        result = self.engine.generate_round({
            "run_id": run_id,
            "idempotency_key": "two-stage-initial-1",
            "action": "initial",
            "edit_mode": "txt2img",
            "seed": 2**64 - 1,
            "change_summary": "Initial confirmed two-stage composition.",
            "plan": self.two_stage_plan(route),
        })
        return run_id, result

    def plan(
        self,
        *,
        max_rounds: int = 3,
        parameters: dict[str, object] | None = None,
        style: str | None = None,
        upscale_policy: str = "off",
        route: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if route is None:
            route = list(self.router.routes.values())[-1]
        return {
            "profile": "standalone-illustration",
            "style": style,
            "intent": "A calm coast at dawn.",
            "positive_prompt": "calm coast at dawn",
            "negative_prompt": "watermark, text",
            "constraints": {"width": 256, "height": 256},
            "model_choice": TEST_MODEL_ID,
            "backend": "webui",
            "authorization_scope": route["authorization_scope"],
            "route_token": route["route_token"],
            "endpoint_identity": route["endpoint_identity"],
            "model_identity_token": route["identity_token"],
            "identity_strength": route["identity_strength"],
            "workflow_template_id": route["workflow_template_id"],
            "workflow_template_version": route["workflow_template_version"],
            "prompt_compiler_id": route["prompt_compiler_id"],
            "prompt_compiler_version": route["prompt_compiler_version"],
            "parameters": parameters or {"mode": "txt2img", "scheduler": "euler"},
            "max_rounds": max_rounds,
            "upscale_policy": upscale_policy,
        }

    def generate_arguments(
        self,
        run_id: str,
        *,
        key: str = "initial-1",
        action: str = "initial",
        seed: int = 42,
        max_rounds: int = 3,
        style: str | None = None,
        upscale_policy: str = "off",
    ) -> dict[str, object]:
        return {
            "run_id": run_id,
            "idempotency_key": key,
            "action": action,
            "edit_mode": "txt2img",
            "seed": seed,
            "change_summary": "Initial candidate." if action == "initial" else "Refine visible detail.",
            "plan": self.plan(
                max_rounds=max_rounds,
                parameters={"steps": 8, "guidance_scale": 6.0} if action == "refine" else None,
                style=style,
                upscale_policy=upscale_policy,
            ),
        }

    def branch_arguments(
        self,
        parent_run_id: str,
        *,
        edit_mode: str,
        max_rounds: int = 1,
    ) -> dict[str, object]:
        arguments: dict[str, object] = {
            "parent_run_id": parent_run_id,
            "parent_round": 1,
            "contract": {
                "preserve": [
                    {"target": "subject identity", "strength": "hard"},
                    {"target": "composition", "strength": "soft"},
                ],
                "change": ["simplify the background"],
            },
            "max_rounds": max_rounds,
            "edit_mode": edit_mode,
        }
        if edit_mode in {"img2img", "inpaint"}:
            arguments["denoising_strength"] = 0.25
        return arguments

    def reviewed_parent(self) -> str:
        parent = self.start(max_rounds=1)
        parent_id = str(parent["run_id"])
        self.engine.generate_round(self.generate_arguments(parent_id, max_rounds=1))
        self.review(parent_id, 1)
        return parent_id

    def branch(self, edit_mode: str) -> str:
        child = self.engine.branch_run(self.branch_arguments(
            self.reviewed_parent(),
            edit_mode=edit_mode,
        ))
        return str(child["run_id"])

    def child_generate_arguments(
        self,
        run_id: str,
        edit_mode: str,
        *,
        mask_id: str | None = None,
        seed: int = 42,
    ) -> dict[str, object]:
        arguments = self.generate_arguments(run_id, max_rounds=1, seed=seed)
        arguments["edit_mode"] = edit_mode
        arguments["plan"]["parameters"] = {"steps": 8, "guidance_scale": 6.0}
        if mask_id is not None:
            arguments["mask_id"] = mask_id
        return arguments

    def start(
        self,
        *,
        max_rounds: int = 3,
        style: str | None = None,
        upscale_policy: str = "off",
    ) -> dict[str, object]:
        return self.engine.start_run(self.start_arguments(
            max_rounds=max_rounds,
            style=style,
            upscale_policy=upscale_policy,
        ))

    def review(
        self,
        run_id: str,
        round_number: int,
        score: int = 4,
        hard_failures: list[str] | None = None,
        *,
        next_action: str = "finalize",
        limb_status: str = "pass",
    ) -> dict[str, object]:
        rubric = self.engine.get_run({"run_id": run_id})["request"]["merged_profile"]["rubric"]
        return self.engine.record_review({
            "run_id": run_id,
            "round_number": round_number,
            "review": {
                "scores": {name: score for name in rubric},
                "hard_failures": hard_failures or [],
                "critique": "Reviewed candidate.",
                "constraint_results": {
                    "width": {"status": "pass", "observation": "Width matches."},
                    "height": {"status": "pass", "observation": "Height matches."},
                },
                "visual_checks": visual_checks(limb_status=limb_status),
                "next_action": next_action,
            },
        })

    def restarted_engine(self) -> AssetRunEngine:
        return AssetRunEngine(
            self.registry,
            RunStore(self.output_root),
            self.runner,
            lambda: self.capabilities,
            self.postprocessor,
            catalog=self.catalog,
            router=self.router,
            compilers=self.compilers,
        )

    def finalization_confirmation(self, run_id: str) -> str:
        run = self.engine.get_run({"run_id": run_id})
        candidate = run.get("finalization_candidate")
        self.assertIsInstance(candidate, dict)
        assert isinstance(candidate, dict)
        confirmation = candidate.get("confirmation")
        self.assertIsInstance(confirmation, str)
        return str(confirmation)

    def test_list_profiles_injects_capabilities_without_mutating_registry(self) -> None:
        catalog_before = self.engine.registry.list_catalog()
        listed = self.engine.list_profiles()
        self.assertEqual(listed["capabilities"], {
            **self.capabilities,
            "postprocessors": {"anime_upscale": {"available": False, "models": []}},
        })
        self.assertEqual(self.engine.registry.list_catalog(), catalog_before)
        self.capabilities["cuda"] = False
        self.capabilities["available_backends"].append("mutated")
        self.assertTrue(listed["capabilities"]["cuda"])
        self.assertEqual(listed["capabilities"]["available_backends"], ["webui", "diffusers"])
        listed["profiles"]["standalone-illustration"]["defaults"]["aspect_ratio"] = "mutated"
        self.assertNotEqual(
            self.engine.registry.list_catalog()["profiles"]["standalone-illustration"]["defaults"]["aspect_ratio"],
            "mutated",
        )

    def test_regional_start_persists_confirmation_and_executes_exact_backend_data(self) -> None:
        arguments = self.regional_start_arguments()
        started = self.engine.start_run(arguments)
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        route = manifest["request"]["route"]
        plan = self.regional_plan(route)

        self.engine.generate_round({
            "run_id": started["run_id"],
            "idempotency_key": "regional-initial-1",
            "action": "initial",
            "edit_mode": "txt2img",
            "seed": 42,
            "change_summary": "Initial confirmed regional composition.",
            "plan": plan,
        })

        persisted = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(
            persisted["request"]["initial_regional_conditioning"],
            arguments["initial_regional_conditioning"],
        )
        backend_request = self.runner.calls[-1]
        self.assertEqual(backend_request["regional_layout"], arguments["constraints"]["regional_layout"])
        self.assertEqual(backend_request["regional_conditioning"], arguments["initial_regional_conditioning"])
        self.assertEqual(backend_request["workflow"]["template_id"], REGIONAL_TEMPLATE_ID)

    def test_regional_start_rejects_route_geometry_drift_before_creating_run(self) -> None:
        arguments = self.regional_start_arguments()
        changed = copy.deepcopy(arguments["constraints"]["regional_layout"])
        changed["copy_region"]["width"] = 0.35
        arguments["constraints"]["regional_layout"] = changed

        with self.assertRaisesRegex(ConflictError, "route_confirmation_mismatch"):
            self.engine.start_run(arguments)

        self.assertFalse((self.output_root / "runs").exists())

    def test_missing_initial_regional_conditioning_creates_no_run(self) -> None:
        arguments = self.regional_start_arguments()
        del arguments["initial_regional_conditioning"]

        with self.assertRaisesRegex(ValidationError, "invalid_regional_conditioning"):
            self.engine.start_run(arguments)

        self.assertFalse((self.output_root / "runs").exists())

    def test_invalid_regional_generation_creates_no_attempt_or_backend_call(self) -> None:
        arguments = self.regional_start_arguments()
        started = self.engine.start_run(arguments)
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        invalid = self.regional_conditioning()
        invalid["subject_strength"] = 3.0

        with self.assertRaisesRegex(ValidationError, "invalid_regional_conditioning"):
            self.engine.generate_round({
                "run_id": started["run_id"],
                "idempotency_key": "invalid-regional-1",
                "action": "initial",
                "edit_mode": "txt2img",
                "seed": 42,
                "change_summary": "Invalid regional request.",
                "plan": self.regional_plan(manifest["request"]["route"], invalid),
            })

        persisted = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(persisted["attempts"], [])
        self.assertEqual(self.runner.calls, [])

    def test_two_stage_success_compiles_both_prompts_and_commits_only_final_preview(self) -> None:
        runner = TwoStageBackendRunner()
        run_id, (_, preview) = self.execute_two_stage(runner)

        request = runner.calls[0]
        output_paths = request["output_paths"]
        self.assertEqual(set(output_paths), {"base", "mask", "final"})
        self.assertEqual(len({str(Path(path).resolve()) for path in output_paths.values()}), 3)
        self.assertTrue(all(Path(path).parent == self.engine.store.run_root(run_id) for path in output_paths.values()))
        self.assertEqual(request["subject_seed"], 0)
        self.assertEqual(request["workflow"]["control_sha256"], request["control_sha256"])
        self.assertEqual(
            request["component_bundle_sha256"],
            self.engine.get_run({"run_id": run_id})["request"]["route"]["component_bundle_sha256"],
        )

        manifest = self.engine.get_run({"run_id": run_id})
        self.assertEqual(len(manifest["rounds"]), 1)
        round_value = manifest["rounds"][0]
        self.assertEqual(round_value["stage_units"], 2)
        self.assertEqual(round_value["pixel_preservation"]["mismatched_pixels"], 0)
        self.assertEqual(round_value["compiled_prompt"]["compiler_id"], "natural-v1")
        self.assertEqual(round_value["compiled_subject_prompt"]["compiler_id"], "natural-v1")
        self.assertEqual(
            round_value["compiled_prompt"]["compiler_version"],
            round_value["compiled_subject_prompt"]["compiler_version"],
        )
        self.assertEqual(Path(round_value["image"]["path"]).name, "round-01.png")
        self.assertIsNotNone(preview)
        self.assertNotIn("preview", round_value["stages"][0]["image"])

    def test_two_stage_backend_result_must_match_route_control_identity(self) -> None:
        route = {
            "backend": "comfyui",
            "endpoint_identity": TEST_ENDPOINT,
            "identity_token": TEST_IDENTITY,
            "identity_strength": "cryptographic",
            "workflow_template_id": TWO_STAGE_TEMPLATE_ID,
            "workflow_template_version": 1,
            "prompt_compiler_id": "natural-v1",
            "prompt_compiler_version": 1,
            "control_sha256": "c" * 64,
            "component_bundle_sha256": "b" * 64,
        }
        model = {"backend_model_id": "actual-loaded-model"}
        result = {
            "backend": "comfyui",
            "endpoint_identity": TEST_ENDPOINT,
            "model_identity_token": TEST_IDENTITY,
            "identity_strength": "cryptographic",
            "workflow_template_id": TWO_STAGE_TEMPLATE_ID,
            "workflow_template_version": 1,
            "prompt_compiler_id": "natural-v1",
            "prompt_compiler_version": 1,
            "model": "actual-loaded-model",
            "control_sha256": "d" * 64,
            "component_bundle_sha256": "b" * 64,
        }

        with self.assertRaises(AssetEngineError) as raised:
            engine_module._validate_locked_backend_result(result, route, model)

        self.assertEqual(raised.exception.code, "invalid_backend_result")
        self.assertEqual(raised.exception.details, {"field": "control_sha256"})

        result["control_sha256"] = "c" * 64
        result["component_bundle_sha256"] = "e" * 64
        with self.assertRaises(AssetEngineError) as bundle_raised:
            engine_module._validate_locked_backend_result(result, route, model)
        self.assertEqual(bundle_raised.exception.details, {"field": "component_bundle_sha256"})

    def test_two_stage_timeout_recovers_exact_job_without_resubmission(self) -> None:
        runner = RecoveringTwoStageBackendRunner()
        self.engine.backend_runner = runner
        started = self.engine.start_run(self.two_stage_start_arguments())
        run_id = str(started["run_id"])
        route = self.engine.get_run({"run_id": run_id})["request"]["route"]
        arguments = {
            "run_id": run_id,
            "idempotency_key": "two-stage-timeout-recovery",
            "action": "initial",
            "edit_mode": "txt2img",
            "seed": 42,
            "change_summary": "Recover the exact submitted backend job.",
            "plan": self.two_stage_plan(route),
        }

        with self.assertRaisesRegex(StateError, "comfyui_job_timed_out"):
            self.engine.generate_round(arguments)

        unresolved = self.engine.get_run({"run_id": run_id})
        self.assertEqual(unresolved["state"], "unresolved")
        self.assertEqual(unresolved["attempts"][-1]["status"], "unresolved")
        self.assertEqual(
            unresolved["attempts"][-1]["backend_job"],
            {"backend": "comfyui", "job_id": "job-two-stage-timeout"},
        )
        self.assertEqual(
            engine_module.recoverable_next_actions(unresolved),
            ["get_run", "generate_round:recover"],
        )

        changed_key = copy.deepcopy(arguments)
        changed_key["idempotency_key"] = "two-stage-duplicate-submit"
        with self.assertRaisesRegex(StateError, "backend_job_unresolved"):
            self.engine.generate_round(changed_key)
        self.assertEqual(len(runner.calls), 1)

        result, _ = self.engine.generate_round(arguments)
        self.assertTrue(result["ok"])
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[1]["recovery_job_id"], "job-two-stage-timeout")
        self.assertEqual(self.engine.get_run({"run_id": run_id})["state"], "generated")

    def test_two_stage_base_only_failure_records_one_retained_stage(self) -> None:
        runner = TwoStageBackendRunner(failure="base_only")
        arguments = self.two_stage_start_arguments()
        self.engine.backend_runner = runner
        started = self.engine.start_run(arguments)
        run_id = str(started["run_id"])
        route = self.engine.get_run({"run_id": run_id})["request"]["route"]

        with self.assertRaisesRegex(AssetEngineError, "Subject stage failed"):
            self.engine.generate_round({
                "run_id": run_id,
                "idempotency_key": "two-stage-base-only",
                "action": "initial",
                "edit_mode": "txt2img",
                "seed": 42,
                "change_summary": "Exercise retained base handling.",
                "plan": self.two_stage_plan(route),
            })

        manifest = self.engine.get_run({"run_id": run_id})
        self.assertEqual(manifest["state"], "partial")
        self.assertEqual(manifest["stage_budget"]["consumed"], 1)
        self.assertEqual([stage["role"] for stage in manifest["attempts"][0]["retained_stages"]], ["base"])

    def test_two_stage_malformed_trailing_output_retains_only_base_and_cleans_residue(self) -> None:
        runner = TwoStageBackendRunner(failure="malformed_final")
        self.engine.backend_runner = runner
        started = self.engine.start_run(self.two_stage_start_arguments())
        run_id = str(started["run_id"])
        route = self.engine.get_run({"run_id": run_id})["request"]["route"]

        with self.assertRaises(AssetEngineError) as raised:
            self.engine.generate_round({
                "run_id": run_id,
                "idempotency_key": "two-stage-malformed-final",
                "action": "initial",
                "edit_mode": "txt2img",
                "seed": 42,
                "change_summary": "Exercise malformed trailing output recovery.",
                "plan": self.two_stage_plan(route),
            })

        self.assertEqual(raised.exception.code, "backend_stage_failed")
        run_root = self.engine.store.run_root(run_id)
        manifest = self.engine.get_run({"run_id": run_id})
        self.assertEqual(manifest["state"], "partial")
        self.assertIsNone(manifest["active_attempt"])
        self.assertEqual(manifest["stage_budget"]["consumed"], 1)
        self.assertEqual(
            [stage["role"] for stage in manifest["attempts"][0]["retained_stages"]],
            ["base"],
        )
        self.assertEqual({path.name for path in run_root.glob("round-01*")}, {"round-01-base.png"})
        self.assertFalse((run_root / ".run.lock").exists())

    def test_two_stage_retention_replace_failure_fails_attempt_and_removes_artifacts(self) -> None:
        runner = TwoStageBackendRunner(failure="base_only")
        self.engine.backend_runner = runner
        started = self.engine.start_run(self.two_stage_start_arguments())
        run_id = str(started["run_id"])
        route = self.engine.get_run({"run_id": run_id})["request"]["route"]
        original_replace = os.replace

        def fail_base_retention(source: object, destination: object) -> None:
            if Path(source).name == "round-01-base.pending.png":
                raise OSError("injected retention replace failure")
            original_replace(source, destination)

        with patch("local_gpu_imagegen.engine.os.replace", side_effect=fail_base_retention):
            with self.assertRaises(AssetEngineError) as raised:
                self.engine.generate_round({
                    "run_id": run_id,
                    "idempotency_key": "two-stage-retention-replace-failure",
                    "action": "initial",
                    "edit_mode": "txt2img",
                    "seed": 42,
                    "change_summary": "Exercise failed retained-artifact promotion.",
                    "plan": self.two_stage_plan(route),
                })

        self.assertEqual(raised.exception.code, "backend_stage_failed")
        run_root = self.engine.store.run_root(run_id)
        manifest = self.engine.get_run({"run_id": run_id})
        self.assertEqual(manifest["state"], "created")
        self.assertIsNone(manifest["active_attempt"])
        self.assertEqual(manifest["attempts"][-1]["status"], "failed")
        self.assertEqual(list(run_root.glob("round-01*")), [])
        self.assertFalse((run_root / ".run.lock").exists())

    def test_two_stage_cleanup_failure_still_fails_attempt_and_retries_cleanup(self) -> None:
        runner = TwoStageBackendRunner(failure="malformed_base")
        self.engine.backend_runner = runner
        started = self.engine.start_run(self.two_stage_start_arguments())
        run_id = str(started["run_id"])
        route = self.engine.get_run({"run_id": run_id})["request"]["route"]
        original_unlink = Path.unlink
        cleanup_failures = 0

        def fail_first_malformed_cleanup(path: Path, *args: object, **kwargs: object) -> None:
            nonlocal cleanup_failures
            if (
                path.name == "round-01-base.pending.png"
                and path.exists()
                and cleanup_failures == 0
            ):
                cleanup_failures += 1
                raise PermissionError("injected cleanup failure")
            original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=fail_first_malformed_cleanup):
            with self.assertRaises(AssetEngineError) as raised:
                self.engine.generate_round({
                    "run_id": run_id,
                    "idempotency_key": "two-stage-cleanup-failure",
                    "action": "initial",
                    "edit_mode": "txt2img",
                    "seed": 42,
                    "change_summary": "Exercise recovery cleanup failure handling.",
                    "plan": self.two_stage_plan(route),
                })

        self.assertEqual(raised.exception.code, "backend_stage_failed")
        self.assertEqual(cleanup_failures, 1)
        run_root = self.engine.store.run_root(run_id)
        manifest = self.engine.get_run({"run_id": run_id})
        self.assertEqual(manifest["state"], "created")
        self.assertIsNone(manifest["active_attempt"])
        self.assertEqual(manifest["attempts"][-1]["status"], "failed")
        self.assertEqual(list(run_root.glob("round-01*")), [])
        self.assertFalse((run_root / ".run.lock").exists())

    def test_two_stage_partial_record_failure_fails_attempt_and_removes_retained_artifacts(self) -> None:
        runner = TwoStageBackendRunner(failure="base_only")
        self.engine.backend_runner = runner
        started = self.engine.start_run(self.two_stage_start_arguments())
        run_id = str(started["run_id"])
        route = self.engine.get_run({"run_id": run_id})["request"]["route"]
        partial_error = AssetEngineError(
            "partial_record_failed",
            "Injected partial manifest failure.",
            "artifact",
        )

        with patch.object(self.engine.store, "record_partial_attempt", side_effect=partial_error):
            with self.assertRaises(AssetEngineError) as raised:
                self.engine.generate_round({
                    "run_id": run_id,
                    "idempotency_key": "two-stage-partial-record-failure",
                    "action": "initial",
                    "edit_mode": "txt2img",
                    "seed": 42,
                    "change_summary": "Exercise failed partial manifest transition.",
                    "plan": self.two_stage_plan(route),
                })

        self.assertEqual(raised.exception.code, "backend_stage_failed")
        run_root = self.engine.store.run_root(run_id)
        manifest = self.engine.get_run({"run_id": run_id})
        self.assertEqual(manifest["state"], "created")
        self.assertIsNone(manifest["active_attempt"])
        self.assertEqual(manifest["attempts"][-1]["status"], "failed")
        self.assertEqual(list(run_root.glob("round-01*")), [])
        self.assertFalse((run_root / ".run.lock").exists())

    def test_two_stage_mask_or_protected_pixel_failure_records_technical_partial(self) -> None:
        for failure, error_code in (
            ("mask_leak", "invalid_two_stage_mask"),
            ("protected_change", "two_stage_pixel_mismatch"),
        ):
            with self.subTest(failure=failure):
                runner = TwoStageBackendRunner(failure=failure)
                arguments = self.two_stage_start_arguments()
                self.engine.backend_runner = runner
                started = self.engine.start_run(arguments)
                run_id = str(started["run_id"])
                route = self.engine.get_run({"run_id": run_id})["request"]["route"]
                with self.assertRaisesRegex(AssetEngineError, error_code):
                    self.engine.generate_round({
                        "run_id": run_id,
                        "idempotency_key": f"two-stage-{failure}",
                        "action": "initial",
                        "edit_mode": "txt2img",
                        "seed": 42,
                        "change_summary": "Exercise technical gate failure.",
                        "plan": self.two_stage_plan(route),
                    })
                manifest = self.engine.get_run({"run_id": run_id})
                self.assertEqual(manifest["state"], "partial")
                self.assertEqual(manifest["stage_budget"]["consumed"], 2)
                self.assertEqual(
                    [stage["role"] for stage in manifest["attempts"][0]["retained_stages"]],
                    ["base", "subject"],
                )

    def test_revision_and_mask_injection_preserves_existing_constructor_arguments(self) -> None:
        revisions = object()
        masks = object()
        engine = AssetRunEngine(
            self.registry,
            self.engine.store,
            self.runner,
            lambda: self.capabilities,
            self.postprocessor,
            revisions=revisions,
            masks=masks,
            catalog=self.catalog,
            router=self.router,
            compilers=self.compilers,
        )

        self.assertIs(engine.registry, self.registry)
        self.assertIs(engine.store, self.engine.store)
        self.assertIs(engine.backend_runner, self.runner)
        self.assertIs(engine.postprocessor, self.postprocessor)
        self.assertIs(engine.revisions, revisions)
        self.assertIs(engine.masks, masks)

    def test_branch_prepare_and_confirm_delegate_to_injected_services(self) -> None:
        class Revisions:
            def branch(self, arguments: dict[str, object]) -> dict[str, object]:
                return {"service": "revisions", "arguments": arguments}

        class Masks:
            def prepare(self, arguments: dict[str, object]) -> tuple[dict[str, object], None]:
                return {"service": "masks", "arguments": arguments}, None

            def confirm(self, arguments: dict[str, object]) -> dict[str, object]:
                return {"service": "confirm", "arguments": arguments}

        engine = AssetRunEngine(
            self.registry,
            self.engine.store,
            self.runner,
            lambda: self.capabilities,
            self.postprocessor,
            revisions=Revisions(),
            masks=Masks(),
            catalog=self.catalog,
            router=self.router,
            compilers=self.compilers,
        )

        self.assertEqual(engine.branch_run({"value": 1})["service"], "revisions")
        self.assertEqual(engine.prepare_mask({"value": 2})[0]["service"], "masks")
        self.assertEqual(engine.confirm_mask({"value": 3})["service"], "confirm")

    def prepare_anime_run(self, *, upscale_policy: str = "auto") -> str:
        started = self.start(style="anime", upscale_policy=upscale_policy)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(
            run_id,
            style="anime",
            upscale_policy=upscale_policy,
        ))
        self.review(run_id, 1)
        return run_id

    def test_list_profiles_reports_sorted_postprocessor_capability_without_upscaling(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime", "realesr-animevideov3-x4"]

        listed = self.engine.list_profiles()

        self.assertEqual(listed["capabilities"]["postprocessors"], {
            "anime_upscale": {
                "available": True,
                "models": ["realesr-animevideov3-x4", "realesrgan-x4plus-anime"],
            },
        })
        self.assertEqual(self.postprocessor.upscale_calls, [])

    def test_start_and_get_return_run_id_rubric_and_deterministic_actions(self) -> None:
        started = self.start()
        self.assertTrue(started["ok"])
        self.assertRegex(started["run_id"], r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
        self.assertEqual(started["max_rounds"], 3)
        self.assertIn("subject_completeness", started["merged_rubric"])
        fetched = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(fetched["recoverable_next_actions"], ["generate_round"])
        self.assertEqual(fetched["request"]["model_choice"], TEST_MODEL_ID)
        self.assertEqual(fetched["request"]["model_record"]["id"], TEST_MODEL_ID)
        self.assertEqual(fetched["request"]["model_record"]["source"], "test-fixture")
        self.assertEqual(fetched["request"]["model_record"]["license_id"], "test-only")
        self.assertEqual(fetched["request"]["upscale_policy"], "off")
        self.assertEqual(fetched["request"]["available_backends"], ["webui", "diffusers"])
        self.assertEqual(fetched["request"]["route"]["identity_token"], TEST_IDENTITY)
        self.assertEqual(fetched["request"]["prompt_compiler_id"], "sd15-tags-v1")
        fetched["request"]["model_record"]["recommended"]["steps"] = 99
        fresh = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(fresh["request"]["model_record"]["recommended"]["steps"], 4)

    def test_generation_rechecks_route_and_never_calls_backend_after_drift(self) -> None:
        run_id = str(self.start()["run_id"])
        self.catalog.drift()

        with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            self.engine.generate_round(self.generate_arguments(run_id))

        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.engine.get_run({"run_id": run_id})["attempts"], [])

    def test_success_retains_route_compiled_prompt_and_records_observation(self) -> None:
        run_id = str(self.start(max_rounds=1)["run_id"])

        result, _ = self.engine.generate_round(self.generate_arguments(run_id, max_rounds=1))

        retained = result["round"]["backend_result"]
        self.assertEqual(retained["model_identity_token"], TEST_IDENTITY)
        self.assertEqual(retained["endpoint_identity"], TEST_ENDPOINT)
        manifest = self.engine.get_run({"run_id": run_id})
        self.assertEqual(manifest["attempts"][0]["route"], manifest["request"]["route"])
        self.assertEqual(manifest["attempts"][0]["compiled_prompt"]["compiler_id"], "sd15-tags-v1")
        self.assertEqual(self.catalog.observations, [(TEST_MODEL_ID, TEST_IDENTITY, "txt2img", run_id)])

    def test_start_rejects_invalid_round_budget_before_creating_run(self) -> None:
        arguments = self.start_arguments(max_rounds=4)
        with self.assertRaises(ValidationError) as raised:
            self.engine.start_run(arguments)
        self.assertEqual(raised.exception.code, "invalid_round_budget")
        self.assertFalse((self.output_root / "runs").exists())

    def test_start_requires_non_empty_model_choice_before_engine_work(self) -> None:
        for value, expected_code in ((None, "missing_argument"), (" ", "invalid_model_choice")):
            with self.subTest(value=value):
                arguments = self.start_arguments()
                if value is None:
                    arguments.pop("model_choice")
                else:
                    arguments["model_choice"] = value
                with patch.object(self.engine, "capability_provider") as capabilities:
                    with self.assertRaises(ValidationError) as raised:
                        self.engine.start_run(arguments)

                self.assertEqual(raised.exception.code, expected_code)
                capabilities.assert_not_called()
                self.assertFalse((self.output_root / "runs").exists())

    def test_start_rejects_model_choice_that_differs_from_route(self) -> None:
        output_root = Path(self.temporary_directory.name) / "production-output"
        engine = AssetRunEngine(
            ProfileRegistry(ROOT / "profiles"),
            RunStore(output_root),
            self.runner,
            lambda: self.capabilities,
            catalog=self.catalog,
            router=self.router,
            compilers=self.compilers,
        )
        arguments = self.start_arguments()
        arguments["model_choice"] = "stabilityai/sd-turbo"

        with self.assertRaises(ConflictError) as raised:
            engine.start_run(arguments)

        self.assertEqual(raised.exception.code, "route_confirmation_expired")
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((output_root / "runs").exists())

    def test_start_rejects_invalid_confirmed_requests_before_creating_run(self) -> None:
        invalid_changes: dict[str, dict[str, object]] = {
            "empty-intent": {"intent": "   "},
            "unknown-backend": {"backend": "comfyui"},
            "invalid-upscale": {"upscale_policy": "sometimes"},
            "zero-budget": {"max_rounds": 0},
            "invalid-constraints": {"constraints": []},
            "empty-style": {"style": ""},
            "unknown-style": {"style": "missing-style"},
            "unknown-profile": {"profile": "missing-profile"},
        }
        for name, changes in invalid_changes.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    output_root = Path(directory) / "output"
                    engine = AssetRunEngine(
                        self.registry,
                        RunStore(output_root),
                        FakeBackendRunner(),
                        lambda: self.capabilities,
                        catalog=self.catalog,
                        router=self.router,
                        compilers=self.compilers,
                    )
                    arguments = {**self.start_arguments(), **changes}
                    with self.assertRaises(AssetEngineError):
                        engine.start_run(arguments)
                    self.assertFalse((output_root / "runs").exists())

    def test_start_rejects_invalid_provider_capabilities(self) -> None:
        for advertised in ([], ["webui", "diffusers", "diffusers"], ["comfyui"]):
            with self.subTest(advertised=advertised):
                with tempfile.TemporaryDirectory() as directory:
                    output_root = Path(directory) / "output"
                    engine = AssetRunEngine(
                        self.registry,
                        RunStore(output_root),
                        FakeBackendRunner(),
                        lambda: {"available_backends": advertised},
                        catalog=self.catalog,
                        router=self.router,
                        compilers=self.compilers,
                    )
                    with self.assertRaises(ValidationError) as raised:
                        engine.start_run(self.start_arguments())
                    self.assertIn(raised.exception.code, {"invalid_capabilities", "invalid_backend"})
                    self.assertFalse((output_root / "runs").exists())

    def test_argument_validation_happens_before_state_mutation(self) -> None:
        with self.assertRaises(ValidationError) as missing:
            self.engine.start_run({})
        self.assertEqual(missing.exception.code, "missing_argument")
        started = self.start()
        invalid = self.generate_arguments(started["run_id"])
        invalid["seed"] = True
        with self.assertRaises(ValidationError) as wrong_type:
            self.engine.generate_round(invalid)
        self.assertEqual(wrong_type.exception.code, "invalid_argument_type")
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["state"], "created")
        self.assertEqual(manifest["attempts"], [])
        self.assertEqual(self.runner.calls, [])

    def test_change_summary_is_required_before_state_mutation(self) -> None:
        for invalid_summary in (None, "   "):
            with self.subTest(change_summary=invalid_summary):
                started = self.start()
                arguments = self.generate_arguments(started["run_id"])
                if invalid_summary is None:
                    arguments.pop("change_summary")
                else:
                    arguments["change_summary"] = invalid_summary

                with self.assertRaises(ValidationError) as raised:
                    self.engine.generate_round(arguments)

                self.assertIn(raised.exception.code, {"missing_argument", "invalid_change_summary"})
                manifest = self.engine.get_run({"run_id": started["run_id"]})
                self.assertEqual(manifest["state"], "created")
                self.assertEqual(manifest["attempts"], [])
                self.assertEqual(self.runner.calls, [])

    def test_one_round_uses_pending_then_atomic_final_name_and_returns_bounded_preview(self) -> None:
        started = self.start()
        data, preview = self.engine.generate_round(self.generate_arguments(started["run_id"]))
        run_root = self.output_root / "runs" / started["run_id"]
        self.assertEqual(len(self.runner.calls), 1)
        request = self.runner.calls[0]
        self.assertEqual(request["model"]["backend_model_id"], "actual-loaded-model")
        self.assertEqual(Path(str(request["output_path"])).name, "round-01.pending.png")
        self.assertFalse((run_root / "round-01.pending.png").exists())
        self.assertTrue((run_root / "round-01.png").is_file())
        self.assertEqual(data["round"]["image"]["path"], "round-01.png")
        self.assertEqual(data["round"]["backend"], "webui")
        self.assertEqual(data["round"]["mode"], "txt2img")
        self.assertEqual(data["round"]["model"], "actual-loaded-model")
        self.assertEqual(data["round"]["backend_result"]["model"], "actual-loaded-model")
        self.assertEqual(data["round"]["backend_result"]["path"], "round-01.png")
        self.assertEqual(data["full_image_path"], str((run_root / "round-01.png").resolve()))
        self.assertIsNotNone(preview)
        self.assertIsNotNone(preview.data_base64)
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["rounds"][0]["preview"]["path"], "round-01-preview.jpg")
        expected_plan = self.plan()
        self.assertIn("generation_plan", manifest["attempts"][0])
        self.assertIn("change_summary", manifest["attempts"][0])
        self.assertEqual(manifest["attempts"][0]["generation_plan"], expected_plan)
        self.assertEqual(manifest["attempts"][0]["change_summary"], "Initial candidate.")
        self.assertEqual(manifest["rounds"][0]["generation_plan"], expected_plan)
        self.assertEqual(manifest["rounds"][0]["change_summary"], "Initial candidate.")

    def test_completed_round_copies_immutable_registry_metadata(self) -> None:
        start_arguments = self.start_arguments(style="anime")
        started = self.engine.start_run(start_arguments)
        generation_arguments = self.generate_arguments(started["run_id"])
        generation_arguments["plan"]["style"] = "anime"

        data, _ = self.engine.generate_round(generation_arguments)

        expected = {
            "profile": {"id": "standalone-illustration", "schema_version": 1},
            "style": {"id": "anime", "schema_version": 1},
            "model": {
                "id": TEST_MODEL_ID,
                "source": "test-fixture",
                "license_id": "test-only",
                "license_url": None,
                "license_status": "approved",
            },
        }
        self.assertEqual(data["round"]["registry_metadata"], expected)
        data["round"]["registry_metadata"]["model"]["source"] = "mutated"
        stored = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(stored["rounds"][0]["registry_metadata"], expected)

    def test_nested_mode_mismatch_is_rejected_before_attempt_or_backend(self) -> None:
        for nested_mode in ("img2img", "inpaint"):
            with self.subTest(nested_mode=nested_mode), tempfile.TemporaryDirectory() as directory:
                runner = FakeBackendRunner()
                engine = AssetRunEngine(
                    self.registry,
                    RunStore(Path(directory) / "output"),
                    runner,
                    lambda: self.capabilities,
                    catalog=self.catalog,
                    router=self.router,
                    compilers=self.compilers,
                )
                started = engine.start_run(self.start_arguments())
                arguments = self.generate_arguments(started["run_id"])
                arguments["plan"]["parameters"]["mode"] = nested_mode

                with self.assertRaises(ValidationError) as raised:
                    engine.generate_round(arguments)

                self.assertEqual(raised.exception.code, "edit_mode_mismatch")
                manifest = engine.get_run({"run_id": started["run_id"]})
                self.assertEqual(manifest["state"], "created")
                self.assertEqual(manifest["attempts"], [])
                self.assertEqual(runner.calls, [])

    def test_root_runs_remain_txt2img(self) -> None:
        run_id = str(self.start(max_rounds=1)["run_id"])

        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=1))

        request = self.runner.calls[-1]
        self.assertEqual(request["mode"], "txt2img")
        self.assertIsNone(request["source_path"])
        self.assertIsNone(request["mask_path"])
        self.assertIsNone(request["strength"])

    def test_child_edit_modes_inject_only_branch_owned_backend_inputs(self) -> None:
        prompt_child = self.branch("prompt-refine")
        self.engine.generate_round(self.child_generate_arguments(prompt_child, "txt2img"))
        prompt_request = self.runner.calls[-1]
        self.assertEqual(prompt_request["mode"], "txt2img")
        self.assertIsNone(prompt_request["source_path"])
        self.assertIsNone(prompt_request["mask_path"])
        self.assertIsNone(prompt_request["strength"])

        img_child = self.branch("img2img")
        self.engine.generate_round(self.child_generate_arguments(img_child, "img2img"))
        img_request = self.runner.calls[-1]
        img_source = Path(str(img_request["source_path"]))
        self.assertEqual(img_request["mode"], "img2img")
        self.assertEqual(img_source.name, "parent-source.png")
        self.assertEqual(img_request["strength"], 0.25)
        self.assertIsNone(img_request["mask_path"])

        inpaint_child = self.branch("inpaint")
        prepared, _ = self.engine.prepare_mask({
            "run_id": inpaint_child,
            "geometry": [{"type": "rectangle", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}],
            "feather_pixels": 0,
        })
        self.engine.confirm_mask({"run_id": inpaint_child, "mask_id": prepared["mask_id"]})
        self.engine.generate_round(self.child_generate_arguments(
            inpaint_child,
            "inpaint",
            mask_id=str(prepared["mask_id"]),
        ))
        inpaint_request = self.runner.calls[-1]
        mask_path = Path(str(inpaint_request["mask_path"]))
        self.assertEqual(inpaint_request["mode"], "inpaint")
        self.assertEqual(Path(str(inpaint_request["source_path"])).name, "parent-source.png")
        self.assertEqual(mask_path.name, "mask-01.png")
        self.assertEqual(inpaint_request["strength"], 0.25)

    def test_inpaint_mask_failures_happen_before_backend_invocation(self) -> None:
        inpaint_child = self.branch("inpaint")
        before = len(self.runner.calls)
        with self.assertRaisesRegex(AssetEngineError, "inpaint_mask_required"):
            self.engine.generate_round(self.child_generate_arguments(inpaint_child, "inpaint"))
        self.assertEqual(len(self.runner.calls), before)

        prepared, _ = self.engine.prepare_mask({
            "run_id": inpaint_child,
            "geometry": [{"type": "rectangle", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}],
        })
        with self.assertRaisesRegex(AssetEngineError, "mask_not_confirmed"):
            self.engine.generate_round(self.child_generate_arguments(
                inpaint_child,
                "inpaint",
                mask_id=str(prepared["mask_id"]),
            ))
        self.assertEqual(len(self.runner.calls), before)

        foreign_child = self.branch("inpaint")
        with self.assertRaisesRegex(AssetEngineError, "mask_not_found"):
            self.engine.generate_round(self.child_generate_arguments(
                foreign_child,
                "inpaint",
                mask_id=str(prepared["mask_id"]),
            ))
        self.assertEqual(len(self.runner.calls), before + 1)

        self.engine.confirm_mask({"run_id": inpaint_child, "mask_id": prepared["mask_id"]})
        Path(str(prepared["mask_path"])).write_bytes(b"changed")
        with self.assertRaisesRegex(AssetEngineError, "mask_changed_since_prepare"):
            self.engine.generate_round(self.child_generate_arguments(
                inpaint_child,
                "inpaint",
                mask_id=str(prepared["mask_id"]),
            ))
        self.assertEqual(len(self.runner.calls), before + 1)

    def test_inpaint_mask_id_participates_in_idempotency_hash(self) -> None:
        child_id = self.branch("inpaint")
        prepared_masks = []
        for x in (0.1, 0.5):
            prepared, _ = self.engine.prepare_mask({
                "run_id": child_id,
                "geometry": [{"type": "rectangle", "x": x, "y": 0.1, "width": 0.2, "height": 0.2}],
            })
            self.engine.confirm_mask({"run_id": child_id, "mask_id": prepared["mask_id"]})
            prepared_masks.append(str(prepared["mask_id"]))
        self.engine.generate_round(self.child_generate_arguments(
            child_id,
            "inpaint",
            mask_id=prepared_masks[0],
        ))
        before = len(self.runner.calls)

        with self.assertRaisesRegex(AssetEngineError, "idempotency_conflict"):
            self.engine.generate_round(self.child_generate_arguments(
                child_id,
                "inpaint",
                mask_id=prepared_masks[1],
            ))

        self.assertEqual(len(self.runner.calls), before)
        manifest = self.engine.get_run({"run_id": child_id})
        self.assertEqual(manifest["rounds"][0]["mask_id"], prepared_masks[0])

    def test_root_and_child_requests_cannot_override_fixed_edit_mode(self) -> None:
        root_id = str(self.start(max_rounds=1)["run_id"])
        before = len(self.runner.calls)
        with self.assertRaisesRegex(AssetEngineError, "root_edit_mode_invalid"):
            self.engine.generate_round(self.child_generate_arguments(root_id, "img2img"))
        self.assertEqual(len(self.runner.calls), before)

        child_id = self.branch("img2img")
        before = len(self.runner.calls)
        with self.assertRaisesRegex(AssetEngineError, "revision_edit_mode_mismatch"):
            self.engine.generate_round(self.child_generate_arguments(child_id, "txt2img"))
        self.assertEqual(len(self.runner.calls), before)

    def test_backend_result_must_match_requested_backend_seed_and_integer_dimensions(self) -> None:
        mismatches = {
            "backend": {"backend": "diffusers"},
            "seed": {"seed": 99},
            "boolean-width": {"width": True},
            "float-height": {"height": 256.0},
        }
        for name, overrides in mismatches.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    output_root = Path(directory) / "output"
                    runner = FakeBackendRunner()
                    runner.result_overrides = overrides
                    engine = AssetRunEngine(
                        self.registry,
                        RunStore(output_root),
                        runner,
                        lambda: self.capabilities,
                        catalog=self.catalog,
                        router=self.router,
                        compilers=self.compilers,
                    )
                    started = engine.start_run(self.start_arguments())
                    with self.assertRaises(AssetEngineError) as raised:
                        engine.generate_round(self.generate_arguments(started["run_id"]))
                    self.assertEqual(raised.exception.code, "invalid_backend_result")
                    manifest = engine.get_run({"run_id": started["run_id"]})
                    self.assertEqual(manifest["rounds"], [])
                    self.assertEqual(manifest["attempts"][-1]["status"], "failed")

    def test_invalid_full_plan_does_not_begin_attempt(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        arguments["plan"]["intent"] = "Different intent."
        with self.assertRaises(ValidationError):
            self.engine.generate_round(arguments)
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["state"], "created")
        self.assertEqual(self.runner.calls, [])

    def test_invalid_derived_plan_values_do_not_begin_attempt(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        arguments["plan"]["parameters"]["width"] = True
        with self.assertRaises(ValidationError) as raised:
            self.engine.generate_round(arguments)
        self.assertEqual(raised.exception.code, "invalid_dimensions")
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["state"], "created")
        self.assertEqual(manifest["attempts"], [])
        self.assertEqual(self.runner.calls, [])

    def test_backend_result_path_must_remain_inside_the_run(self) -> None:
        started = self.start()
        self.runner.path_override = self.output_root.parent / "escape.png"
        with self.assertRaises(AssetEngineError) as raised:
            self.engine.generate_round(self.generate_arguments(started["run_id"]))
        self.assertEqual(raised.exception.code, "path_outside_output_root")
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["rounds"], [])
        self.assertEqual(manifest["attempts"][-1]["status"], "failed")

    def test_backend_failure_is_recorded_without_consuming_round(self) -> None:
        started = self.start()
        self.runner.exit_code = 9
        self.runner.stderr = "backend unavailable"
        with self.assertRaises(AssetEngineError) as raised:
            self.engine.generate_round(self.generate_arguments(started["run_id"]))
        self.assertEqual(raised.exception.code, "backend_command_failed")
        failed = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(failed["state"], "created")
        self.assertEqual(failed["rounds"], [])
        self.assertEqual(failed["attempts"][-1]["status"], "failed")
        self.assertEqual(failed["attempts"][-1]["generation_plan"], self.plan())
        self.assertEqual(failed["attempts"][-1]["change_summary"], "Initial candidate.")
        self.runner.exit_code = 0
        data, _ = self.engine.generate_round(self.generate_arguments(started["run_id"], key="initial-2"))
        self.assertEqual(data["round"]["round_number"], 1)

    def test_unexpected_exception_releases_owned_attempt_lock(self) -> None:
        started = self.start()
        with patch("local_gpu_imagegen.engine.validate_backend_result", side_effect=RuntimeError("unexpected")):
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                self.engine.generate_round(self.generate_arguments(started["run_id"]))
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertEqual(manifest["attempts"][-1]["status"], "failed")
        self.assertFalse((self.output_root / "runs" / started["run_id"] / ".run.lock").exists())

    def test_preview_warning_keeps_full_image_and_is_appended_to_run(self) -> None:
        started = self.start()
        unavailable = PreviewResult(None, None, None, None, None, "preview_unavailable:test")
        with patch("local_gpu_imagegen.engine.create_preview", return_value=unavailable):
            data, preview = self.engine.generate_round(self.generate_arguments(started["run_id"]))
        self.assertEqual(preview, unavailable)
        self.assertTrue(Path(data["full_image_path"]).is_file())
        manifest = self.engine.get_run({"run_id": started["run_id"]})
        self.assertIn("preview_unavailable:test", manifest["warnings"])

    def test_crash_after_marked_image_rebuilds_preview_without_backend(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        with patch("local_gpu_imagegen.engine.create_preview", side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        with patch("local_gpu_imagegen.run_store.is_process_alive", return_value=False):
            data, preview = self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(data["round"]["round_number"], 1)
        self.assertIsNotNone(preview)

    def test_completed_retry_revalidates_artifact_and_never_calls_backend(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        preview_path = Path(first["full_image_path"]).with_name("round-01-preview.jpg")
        preview_path.unlink(missing_ok=True)
        second, preview = self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(second["round"]["round_number"], 1)
        self.assertIsNotNone(preview)

    def test_completed_retry_accepts_legacy_dot_preview_manifest_path(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        arguments = self.generate_arguments(run_id)
        first, _ = self.engine.generate_round(arguments)
        run_root = self.output_root / "runs" / run_id
        current = run_root / first["round"]["preview"]["path"]
        legacy = run_root / "round-01.preview.jpg"
        os.replace(current, legacy)

        def retain_legacy(manifest: dict[str, object]) -> None:
            manifest["rounds"][0]["preview"]["path"] = legacy.name

        self.engine.store.update(run_id, retain_legacy)
        with patch("local_gpu_imagegen.engine.create_preview") as rebuild:
            second, preview = self.engine.generate_round(arguments)

        rebuild.assert_not_called()
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(second["round"]["preview"]["path"], legacy.name)
        self.assertIsNotNone(preview)

    def test_completed_retry_rebuilds_untrusted_preview_without_returning_png_bytes(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        image_path = Path(first["full_image_path"])
        preview_path = self.output_root / "runs" / started["run_id"] / first["round"]["preview"]["path"]
        self.assertIn("sha256", first["round"]["preview"])

        def full_png() -> None:
            preview_path.write_bytes(image_path.read_bytes())

        def oversized() -> None:
            preview_path.write_bytes(b"\xff\xd8" + b"x" * MAX_PREVIEW_BYTES + b"\xff\xd9")

        def non_jpeg() -> None:
            preview_path.write_bytes(b"not-a-jpeg")

        def corrupt_jpeg() -> None:
            preview_path.write_bytes(b"\xff\xd8truncated")

        def hash_mismatch() -> None:
            contents = bytearray(preview_path.read_bytes())
            contents[len(contents) // 2] ^= 1
            preview_path.write_bytes(contents)

        def hard_link_to_full() -> None:
            preview_path.unlink()
            os.link(image_path, preview_path)

        replacements = (
            ("full-png", full_png),
            ("oversized", oversized),
            ("non-jpeg", non_jpeg),
            ("corrupt-jpeg", corrupt_jpeg),
            ("hash-mismatch", hash_mismatch),
            ("hard-link", hard_link_to_full),
        )
        for name, replace_preview in replacements:
            with self.subTest(name=name):
                replace_preview()
                _, preview = self.engine.generate_round(arguments)
                self.assertEqual(len(self.runner.calls), 1)
                self.assertIsNotNone(preview)
                self.assertEqual(preview.mime_type, "image/jpeg")
                preview_bytes = base64.b64decode(preview.data_base64)
                self.assertTrue(preview_bytes.startswith(b"\xff\xd8"))
                self.assertTrue(preview_bytes.endswith(b"\xff\xd9"))
                self.assertNotEqual(preview_bytes, image_path.read_bytes())

    def test_invalid_completed_preview_returns_warning_without_data_when_rebuild_is_unavailable(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        preview_path = self.output_root / "runs" / started["run_id"] / first["round"]["preview"]["path"]
        preview_path.write_bytes(Path(first["full_image_path"]).read_bytes())
        unavailable = PreviewResult(None, None, None, None, None, "preview_unavailable:test-rebuild")
        with patch("local_gpu_imagegen.engine.create_preview", return_value=unavailable):
            _, preview = self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(preview.warning, "preview_unavailable:test-rebuild")
        self.assertIsNone(preview.data_base64)

    def test_escaping_completed_preview_path_is_rebuilt_without_backend(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)

        def escape_preview(manifest: dict[str, object]) -> None:
            manifest["rounds"][0]["preview"]["path"] = "../outside.jpg"

        self.engine.store.update(started["run_id"], escape_preview)
        _, preview = self.engine.generate_round(arguments)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertIsNotNone(preview.data_base64)
        self.assertNotEqual(base64.b64decode(preview.data_base64), Path(first["full_image_path"]).read_bytes())

    def test_completed_preview_returns_bytes_and_hash_from_one_descriptor(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        run_root = self.output_root / "runs" / started["run_id"]
        preview_path = run_root / first["round"]["preview"]["path"]
        trusted_bytes = preview_path.read_bytes()
        attacker_bytes = b"\xff\xd8attacker-controlled-preview\xff\xd9"
        held_path = preview_path.with_name("held-trusted-preview.jpg")
        original_read_bytes = Path.read_bytes

        def swap_for_read(path: Path) -> bytes:
            if path.resolve() != preview_path.resolve():
                return original_read_bytes(path)
            os.replace(preview_path, held_path)
            preview_path.write_bytes(attacker_bytes)
            try:
                return original_read_bytes(preview_path)
            finally:
                preview_path.unlink()
                os.replace(held_path, preview_path)

        with patch.object(Path, "read_bytes", new=swap_for_read):
            data, preview = self.engine.generate_round(arguments)

        returned = base64.b64decode(preview.data_base64)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(returned, trusted_bytes)
        self.assertNotEqual(returned, attacker_bytes)
        self.assertEqual(data["round"]["preview"]["sha256"], hashlib.sha256(returned).hexdigest())

    def test_completed_preview_path_swap_after_descriptor_read_forces_rebuild(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        run_root = self.output_root / "runs" / started["run_id"]
        preview_path = run_root / first["round"]["preview"]["path"]
        held_path = preview_path.with_name("swapped-trusted-preview.jpg")
        attacker_bytes = b"\xff\xd8replacement-after-read\xff\xd9"

        def swap_and_reject(path: Path, descriptor_stat: object) -> bool:
            os.replace(path, held_path)
            path.write_bytes(attacker_bytes)
            return False

        with patch(
            "local_gpu_imagegen.engine._path_matches_open_file",
            create=True,
            side_effect=swap_and_reject,
        ) as identity_check:
            data, preview = self.engine.generate_round(arguments)

        returned = base64.b64decode(preview.data_base64)
        self.assertEqual(identity_check.call_count, 1)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertNotEqual(returned, attacker_bytes)
        self.assertEqual(returned, preview_path.read_bytes())
        self.assertEqual(data["round"]["preview"]["sha256"], hashlib.sha256(returned).hexdigest())

    def test_completed_preview_internal_symlink_is_rebuilt_when_supported(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        run_root = self.output_root / "runs" / started["run_id"]
        preview_path = run_root / first["round"]["preview"]["path"]
        target_path = preview_path.with_name("internal-preview-target.jpg")
        os.replace(preview_path, target_path)
        try:
            os.symlink(target_path.name, preview_path, target_is_directory=False)
        except OSError as error:
            os.replace(target_path, preview_path)
            self.skipTest(f"Symlink creation is unavailable: {error}")

        with patch("local_gpu_imagegen.engine.create_preview", wraps=engine_module.create_preview) as rebuild:
            _, preview = self.engine.generate_round(arguments)

        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(rebuild.call_count, 1)
        self.assertFalse(preview_path.is_symlink())
        self.assertEqual(base64.b64decode(preview.data_base64), preview_path.read_bytes())

    def test_completed_preview_checks_manifest_raw_path_not_only_resolved_target(self) -> None:
        started = self.start()
        arguments = self.generate_arguments(started["run_id"])
        first, _ = self.engine.generate_round(arguments)
        run_root = self.output_root / "runs" / started["run_id"]
        target_path = run_root / first["round"]["preview"]["path"]
        raw_path = run_root / "manifest-preview-link.jpg"

        def nominate_raw_path(manifest: dict[str, object]) -> None:
            manifest["rounds"][0]["preview"]["path"] = raw_path.name

        self.engine.store.update(started["run_id"], nominate_raw_path)
        original_ensure = engine_module.ensure_within

        def resolve_manifest_link(root: Path, candidate: Path) -> Path:
            if candidate.name == raw_path.name:
                return target_path.resolve()
            return original_ensure(root, candidate)

        def raw_path_is_link(path: Path) -> bool:
            return path.name == raw_path.name

        with (
            patch("local_gpu_imagegen.engine.ensure_within", side_effect=resolve_manifest_link),
            patch("local_gpu_imagegen.engine._path_is_link_like", side_effect=raw_path_is_link) as link_check,
            patch("local_gpu_imagegen.engine.create_preview", wraps=engine_module.create_preview) as rebuild,
        ):
            _, preview = self.engine.generate_round(arguments)

        self.assertIn(raw_path.name, [call.args[0].name for call in link_check.call_args_list])
        self.assertEqual(rebuild.call_count, 1)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(base64.b64decode(preview.data_base64), target_path.read_bytes())

    def test_auto_policy_without_explicit_postprocess_never_calls_adapter(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        run_id = self.prepare_anime_run()

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Keep the reviewed original.",
            "confirmation": self.finalization_confirmation(run_id),
        })

        self.assertEqual(self.postprocessor.available_calls, 0)
        self.assertEqual(self.postprocessor.upscale_calls, [])
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertNotIn("postprocess", finalized["final"])

    def test_engine_rejects_non_exact_postprocess_before_adapter_work(self) -> None:
        cases = (
            {},
            {"type": "anime_upscale"},
            {"model": "realesrgan-x4plus-anime"},
            {"type": "anime_upscale", "model": "realesrgan-x4plus-anime", "extra": True},
            {"type": "other", "model": "realesrgan-x4plus-anime"},
            {"type": "anime_upscale", "model": "../../model"},
        )
        for index, postprocess in enumerate(cases):
            with self.subTest(postprocess=postprocess):
                run_id = self.prepare_anime_run()
                with self.assertRaises(ValidationError) as raised:
                    self.engine.finalize_run({
                        "run_id": run_id,
                        "round_number": 1,
                        "summary": f"Invalid request {index}.",
                        "confirmation": self.finalization_confirmation(run_id),
                        "postprocess": postprocess,
                    })
                self.assertEqual(raised.exception.code, "invalid_postprocess")
                self.assertEqual(self.engine.get_run({"run_id": run_id})["state"], "reviewed")
                self.assertEqual(self.postprocessor.available_calls, 0)
                self.assertEqual(self.postprocessor.upscale_calls, [])

    def test_explicit_postprocess_rejects_off_policy_before_adapter_work(self) -> None:
        run_id = self.prepare_anime_run(upscale_policy="off")

        with self.assertRaises(ValidationError) as raised:
            self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Upscale is disabled.",
                "confirmation": self.finalization_confirmation(run_id),
                "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
            })

        self.assertEqual(raised.exception.code, "postprocess_disabled")
        self.assertEqual(self.postprocessor.available_calls, 0)
        self.assertEqual(self.postprocessor.upscale_calls, [])

    def test_explicit_postprocess_rejects_non_anime_style_before_adapter_work(self) -> None:
        started = self.start(upscale_policy="auto")
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, upscale_policy="auto"))
        self.review(run_id, 1)

        with self.assertRaises(ValidationError) as raised:
            self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Style is not anime.",
                "confirmation": self.finalization_confirmation(run_id),
                "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
            })

        self.assertEqual(raised.exception.code, "postprocess_requires_anime_style")
        self.assertEqual(self.postprocessor.available_calls, 0)
        self.assertEqual(self.postprocessor.upscale_calls, [])

    def test_successful_anime_postprocess_retains_original_and_records_final_metadata(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Publish the faithful 4x result.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        metadata = finalized["final"]["postprocess"]
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["type"], "anime_upscale")
        self.assertEqual(metadata["model"], "realesrgan-x4plus-anime")
        self.assertEqual(metadata["scale"], 4)
        self.assertEqual(metadata["source"]["path"], "final.png")
        self.assertEqual(metadata["output"]["path"], "final-upscaled.png")
        self.assertEqual((metadata["source"]["width"], metadata["source"]["height"]), (256, 256))
        self.assertEqual((metadata["output"]["width"], metadata["output"]["height"]), (1024, 1024))
        self.assertEqual(metadata["source"]["sha256"], hashlib.sha256((run_root / "final.png").read_bytes()).hexdigest())
        self.assertEqual(metadata["output"]["sha256"], hashlib.sha256((run_root / "final-upscaled.png").read_bytes()).hexdigest())
        self.assertEqual(finalized["final"]["image"]["path"], "final.png")
        self.assertEqual(finalized["final"]["path"], "final-upscaled.png")
        self.assertEqual(finalized["full_image_path"], str((run_root / "final-upscaled.png").resolve()))
        self.assertTrue((run_root / "final.png").is_file())
        self.assertTrue((run_root / "final-upscaled.png").is_file())
        self.assertFalse((run_root / "final-upscaled.pending.png").exists())

    def test_unavailable_postprocess_warns_and_returns_original_final(self) -> None:
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Retain the original when unavailable.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        self.assertIn("postprocess_unavailable", finalized["warnings"])
        self.assertEqual(finalized["final"]["postprocess"]["status"], "unavailable")
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertEqual(finalized["full_image_path"], str((run_root / "final.png").resolve()))
        self.assertTrue((run_root / "final.png").is_file())
        self.assertFalse((run_root / "final-upscaled.png").exists())
        self.assertEqual(self.postprocessor.upscale_calls, [])
        self.assertIn("postprocess_unavailable", self.engine.get_run({"run_id": run_id})["warnings"])

    def test_failed_postprocess_warns_returns_original_and_removes_pending_residue(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic failure.",
            "postprocess",
        )
        self.postprocessor.leave_pending_on_failure = True
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Retain the original after failure.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertEqual(finalized["final"]["postprocess"]["status"], "failed")
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertEqual(finalized["full_image_path"], str((run_root / "final.png").resolve()))
        self.assertFalse((run_root / "final-upscaled.pending.png").exists())
        self.assertFalse((run_root / "final-upscaled.png").exists())

    def test_empty_directory_postprocess_residue_keeps_finalized_original(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic directory residue.",
            "postprocess",
        )

        def leave_directories(source: Path, destination: Path) -> None:
            destination.mkdir()
            (destination.parent / "final-upscaled.pending.png").mkdir()

        self.postprocessor.failure_artifact_writer = leave_directories
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        original_hash = hashlib.sha256((run_root / "round-01.png").read_bytes()).hexdigest()

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Fall back from directory residue.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        self.assertEqual(finalized["state"], "finalized")
        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertNotIn("PermissionError", json.dumps(finalized))
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertEqual(hashlib.sha256((run_root / "final.png").read_bytes()).hexdigest(), original_hash)
        self.assertFalse((run_root / "final-upscaled.png").exists())
        self.assertFalse((run_root / "final-upscaled.pending.png").exists())

    def test_junction_postprocess_residue_removes_links_without_touching_targets(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic junction residue.",
            "postprocess",
        )
        target_root = Path(self.temporary_directory.name) / "junction-targets"
        output_target = target_root / "output"
        pending_target = target_root / "pending"
        output_target.mkdir(parents=True)
        pending_target.mkdir()
        (output_target / "keep.txt").write_text("output target", encoding="utf-8")
        (pending_target / "keep.txt").write_text("pending target", encoding="utf-8")

        def leave_junctions(source: Path, destination: Path) -> None:
            create_directory_alias(destination, output_target)
            create_directory_alias(destination.parent / "final-upscaled.pending.png", pending_target)

        self.postprocessor.failure_artifact_writer = leave_junctions
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        original_hash = hashlib.sha256((run_root / "round-01.png").read_bytes()).hexdigest()

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Fall back without traversing junctions.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        self.assertEqual(finalized["state"], "finalized")
        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertNotIn("PermissionError", json.dumps(finalized))
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertEqual(hashlib.sha256((run_root / "final.png").read_bytes()).hexdigest(), original_hash)
        self.assertFalse(os.path.lexists(run_root / "final-upscaled.png"))
        self.assertFalse(os.path.lexists(run_root / "final-upscaled.pending.png"))
        self.assertEqual((output_target / "keep.txt").read_text(encoding="utf-8"), "output target")
        self.assertEqual((pending_target / "keep.txt").read_text(encoding="utf-8"), "pending target")

    def test_nonremovable_postprocess_residue_persists_sanitized_cleanup_warning(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic nonremovable residue.",
            "postprocess",
        )

        def leave_directories(source: Path, destination: Path) -> None:
            destination.mkdir()
            (destination.parent / "final-upscaled.pending.png").mkdir()

        self.postprocessor.failure_artifact_writer = leave_directories
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        original_hash = hashlib.sha256((run_root / "round-01.png").read_bytes()).hexdigest()
        original_rmdir = os.rmdir

        def deny_postprocess_cleanup(path: object, *args: object, **kwargs: object) -> None:
            if Path(path).name in {"final-upscaled.png", "final-upscaled.pending.png"}:
                raise PermissionError("private cleanup location")
            original_rmdir(path, *args, **kwargs)

        with patch("local_gpu_imagegen.postprocess.os.rmdir", side_effect=deny_postprocess_cleanup):
            finalized = self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Persist a sanitized cleanup warning.",
                "confirmation": self.finalization_confirmation(run_id),
                "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
            })

        serialized = json.dumps(finalized)
        self.assertEqual(finalized["state"], "finalized")
        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertIn("postprocess_cleanup_failed", finalized["warnings"])
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertEqual(hashlib.sha256((run_root / "final.png").read_bytes()).hexdigest(), original_hash)
        self.assertNotIn("PermissionError", serialized)
        self.assertNotIn("private cleanup location", serialized)
        self.assertTrue((run_root / "final-upscaled.png").is_dir())
        self.assertTrue((run_root / "final-upscaled.pending.png").is_dir())
        persisted = self.engine.get_run({"run_id": run_id})
        self.assertIn("postprocess_cleanup_failed", persisted["warnings"])

    def test_postprocess_capability_failure_warns_and_keeps_original_final(self) -> None:
        self.postprocessor.available_failure = OSError("capability probe failed")
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Retain the original after capability failure.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertEqual(finalized["final"]["postprocess"]["status"], "failed")
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertEqual(finalized["full_image_path"], str((run_root / "final.png").resolve()))
        self.assertTrue((run_root / "final.png").is_file())
        self.assertEqual(self.postprocessor.upscale_calls, [])

    def test_failed_postprocess_restores_original_when_adapter_mutates_source(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic mutating failure.",
            "postprocess",
        )
        self.postprocessor.mutate_source_on_failure = True
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        original_hash = hashlib.sha256((run_root / "round-01.png").read_bytes()).hexdigest()

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Restore the immutable original.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertEqual(hashlib.sha256((run_root / "final.png").read_bytes()).hexdigest(), original_hash)
        self.assertEqual(finalized["final"]["image"]["sha256"], original_hash)

    def test_failed_postprocess_restores_original_after_source_becomes_directory(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic source directory replacement.",
            "postprocess",
        )

        def replace_source_with_directory(source: Path, destination: Path) -> None:
            source.unlink()
            source.mkdir()

        self.postprocessor.failure_artifact_writer = replace_source_with_directory
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        original_hash = hashlib.sha256((run_root / "round-01.png").read_bytes()).hexdigest()

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Restore the original after a source directory replacement.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        serialized = json.dumps(finalized)
        restored = run_root / "final.png"
        self.assertEqual(finalized["state"], "finalized")
        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertTrue(restored.is_file())
        self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(finalized["final"]["image"]["sha256"], original_hash)
        restored_metadata = validate_png(restored, 256, 256)
        self.assertEqual((restored_metadata["width"], restored_metadata["height"]), (256, 256))
        self.assertNotIn("PermissionError", serialized)

    def test_failed_postprocess_restores_original_after_source_becomes_junction(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic source junction replacement.",
            "postprocess",
        )
        target = Path(self.temporary_directory.name) / "source-junction-target"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("external target", encoding="utf-8")

        def replace_source_with_junction(source: Path, destination: Path) -> None:
            source.unlink()
            create_directory_alias(source, target)

        self.postprocessor.failure_artifact_writer = replace_source_with_junction
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        original_hash = hashlib.sha256((run_root / "round-01.png").read_bytes()).hexdigest()

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Restore the original without traversing a source junction.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        serialized = json.dumps(finalized)
        restored = run_root / "final.png"
        self.assertEqual(finalized["state"], "finalized")
        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertEqual(finalized["final"]["path"], "final.png")
        self.assertTrue(restored.is_file())
        self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(finalized["final"]["image"]["sha256"], original_hash)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external target")
        self.assertNotIn("PermissionError", serialized)

    def test_nonremovable_source_junction_returns_sanitized_failure(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic nonremovable source junction.",
            "postprocess",
        )
        target = Path(self.temporary_directory.name) / "nonremovable-source-target"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("external target", encoding="utf-8")

        def replace_source_with_junction(source: Path, destination: Path) -> None:
            source.unlink()
            create_directory_alias(source, target)

        self.postprocessor.failure_artifact_writer = replace_source_with_junction
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        manifest_before = self.engine.get_run({"run_id": run_id})
        original_rmdir = os.rmdir

        def deny_source_cleanup(path: object, *args: object, **kwargs: object) -> None:
            if Path(path).name == "final.png":
                raise PermissionError("private source cleanup location")
            original_rmdir(path, *args, **kwargs)

        with patch("local_gpu_imagegen.postprocess.os.rmdir", side_effect=deny_source_cleanup):
            with self.assertRaises(AssetEngineError) as raised:
                self.engine.finalize_run({
                    "run_id": run_id,
                    "round_number": 1,
                    "summary": "Keep diagnostic truth when source recovery is blocked.",
                    "confirmation": self.finalization_confirmation(run_id),
                    "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
                })

        serialized = json.dumps({"code": raised.exception.code, "details": raised.exception.details})
        manifest_after = self.engine.get_run({"run_id": run_id})
        self.assertEqual(raised.exception.code, "postprocess_failed")
        self.assertEqual(raised.exception.details.get("cleanup_warning"), "postprocess_cleanup_failed")
        self.assertNotIn("PermissionError", serialized)
        self.assertNotIn("private source cleanup location", serialized)
        self.assertEqual(manifest_after["manifest_revision"], manifest_before["manifest_revision"])
        self.assertEqual(manifest_after.get("final"), manifest_before.get("final"))
        self.assertTrue(os.path.lexists(run_root / "final.png"))
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external target")

    def test_postprocess_pending_alias_resolution_cannot_delete_original_final(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        self.postprocessor.failure = AssetEngineError(
            "postprocess_failed",
            "Synthetic failure.",
            "postprocess",
        )
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        original_ensure_within = engine_module.ensure_within

        def alias_pending(root: Path, candidate: Path) -> Path:
            if Path(candidate).name == "final-upscaled.pending.png":
                return (run_root / "final.png").resolve()
            return original_ensure_within(root, candidate)

        with patch("local_gpu_imagegen.engine.ensure_within", side_effect=alias_pending):
            finalized = self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Keep exact final artifact names.",
                "confirmation": self.finalization_confirmation(run_id),
                "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
            })

        self.assertIn("postprocess_failed", finalized["warnings"])
        self.assertTrue((run_root / "final.png").is_file())
        self.assertEqual(finalized["final"]["path"], "final.png")

    def test_intermediate_cleanup_preserves_original_and_upscaled_final_references(self) -> None:
        self.postprocessor.models = ["realesrgan-x4plus-anime"]
        run_id = self.prepare_anime_run()
        run_root = self.output_root / "runs" / run_id
        self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Publish and clean intermediates.",
            "confirmation": self.finalization_confirmation(run_id),
            "postprocess": {"type": "anime_upscale", "model": "realesrgan-x4plus-anime"},
        })

        self.engine.cleanup_run({"run_id": run_id, "scope": "intermediates", "confirmation": run_id})

        cleaned = self.engine.get_run({"run_id": run_id})
        self.assertTrue((run_root / "final.png").is_file())
        self.assertTrue((run_root / "final-upscaled.png").is_file())
        self.assertEqual(cleaned["final"]["image"]["path"], "final.png")
        self.assertEqual(cleaned["final"]["path"], "final-upscaled.png")
        self.assertEqual(cleaned["final"]["postprocess"]["source"]["path"], "final.png")
        self.assertEqual(cleaned["final"]["postprocess"]["output"]["path"], "final-upscaled.png")

    def test_eligible_review_returns_candidate_not_acceptance(self) -> None:
        started = self.start(max_rounds=2)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=2))

        reviewed = self.review(run_id, 1)

        candidate = reviewed["finalization_candidate"]
        self.assertEqual(candidate["quality_status"], "candidate")
        self.assertEqual(candidate["image_sha256"], reviewed["rounds"][0]["image"]["sha256"])
        self.assertNotIn("accepted", json.dumps(candidate))

    def test_get_run_recovers_the_same_candidate_after_restart(self) -> None:
        started = self.start(max_rounds=2)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=2))
        reviewed = self.review(run_id, 1)

        recovered = self.restarted_engine().get_run({"run_id": run_id})

        self.assertEqual(recovered["finalization_candidate"], reviewed["finalization_candidate"])

    def test_fused_anatomy_rejection_keeps_same_run_budget_and_has_no_candidate(self) -> None:
        started = self.start(max_rounds=2)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=2))

        reviewed = self.review(
            run_id,
            1,
            score=2,
            hard_failures=["severe_anatomy"],
            next_action="refine",
            limb_status="fail",
        )

        self.assertNotIn("finalization_candidate", reviewed)
        self.assertEqual(
            reviewed["recoverable_next_actions"],
            ["generate_round:refine", "generate_round:explore"],
        )
        self.assertEqual(reviewed["request"]["max_rounds"], 2)
        self.assertEqual(len(reviewed["rounds"]), 1)

    def test_finalize_requires_exact_candidate_confirmation_before_copy(self) -> None:
        started = self.start(max_rounds=2)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=2))
        reviewed = self.review(run_id, 1)
        run_root = self.output_root / "runs" / run_id
        manifest_path = run_root / "manifest.json"
        before = manifest_path.read_bytes()
        exact = reviewed["finalization_candidate"]["confirmation"]

        for confirmation in (None, "wrong", exact.replace(":1:", ":2:")):
            arguments: dict[str, object] = {
                "run_id": run_id,
                "round_number": 1,
                "summary": "Selected candidate.",
            }
            if confirmation is not None:
                arguments["confirmation"] = confirmation

            with self.subTest(confirmation=confirmation), self.assertRaisesRegex(
                ValidationError,
                "missing_argument|finalization_confirmation_mismatch",
            ):
                self.engine.finalize_run(arguments)

            self.assertEqual(manifest_path.read_bytes(), before)
            self.assertFalse((run_root / "final.png").exists())

    def test_exact_candidate_confirmation_publishes_selected_bytes(self) -> None:
        started = self.start(max_rounds=2)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=2))
        reviewed = self.review(run_id, 1)

        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Selected candidate.",
            "confirmation": reviewed["finalization_candidate"]["confirmation"],
        })

        self.assertEqual(finalized["final"]["quality_status"], "accepted")
        self.assertEqual(
            finalized["final"]["image"]["sha256"],
            reviewed["finalization_candidate"]["image_sha256"],
        )

    def test_nominated_eligible_round_is_published_even_when_later_round_scores_higher(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        first_review = self.review(run_id, 1, score=3)
        self.engine.generate_round(self.generate_arguments(run_id, key="refine-1", action="refine"))
        self.review(run_id, 2, score=5)
        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Nominated reviewed result.",
            "confirmation": first_review["finalization_candidate"]["confirmation"],
        })
        run_root = self.output_root / "runs" / run_id
        self.assertEqual(finalized["final"]["round_number"], 1)
        self.assertEqual(finalized["final"]["quality_status"], "accepted")
        self.assertEqual(finalized["final"]["image"]["path"], "final.png")
        self.assertTrue((run_root / "final.png").is_file())
        self.assertFalse((run_root / "final.pending.png").exists())

    def test_nominated_ineligible_round_cannot_use_an_accepted_round_confirmation(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        self.review(run_id, 1, score=5, hard_failures=["missing_subject"])
        self.engine.generate_round(self.generate_arguments(run_id, key="refine-1", action="refine"))
        second_review = self.review(run_id, 2, score=5)

        with self.assertRaisesRegex(ValidationError, "finalization_confirmation_mismatch"):
            self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "User nominated the first reviewed round.",
                "confirmation": second_review["finalization_candidate"]["confirmation"],
            })

        self.assertFalse((self.output_root / "runs" / run_id / "final.png").exists())
        self.assertEqual(self.engine.get_run({"run_id": run_id})["state"], "reviewed")

    def test_early_finalize_accepts_eligible_round(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        reviewed = self.review(run_id, 1)
        finalized = self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Accepted early.",
            "confirmation": reviewed["finalization_candidate"]["confirmation"],
        })
        self.assertEqual(finalized["final"]["quality_status"], "accepted")

    def test_exhausted_custom_budget_does_not_publish_an_ineligible_round(self) -> None:
        started = self.start(max_rounds=1)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=1))
        self.review(run_id, 1, score=5, hard_failures=["missing_subject"])
        with self.assertRaisesRegex(ValidationError, "finalization_confirmation_mismatch"):
            self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Budget exhausted.",
                "confirmation": f"finalize:{run_id}:1:{'a' * 64}",
            })
        recovered = self.engine.get_run({"run_id": run_id})
        self.assertEqual(recovered["request"]["max_rounds"], 1)
        self.assertEqual(recovered["recoverable_next_actions"], ["get_run"])

    def test_bundled_profile_low_critical_score_needs_user_review(self) -> None:
        started = self.start(max_rounds=1)
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id, max_rounds=1))
        rubric = self.engine.get_run({"run_id": run_id})["request"]["merged_profile"]["rubric"]
        scores = {name: 5 for name in rubric}
        scores["subject_completeness"] = 2
        self.engine.record_review({
            "run_id": run_id,
            "round_number": 1,
            "review": {
                "scores": scores,
                "hard_failures": [],
                "critique": "The requested subject is incomplete.",
                "constraint_results": {
                    "width": {"status": "pass", "observation": "Width matches."},
                    "height": {"status": "pass", "observation": "Height matches."},
                },
                "visual_checks": visual_checks(),
                "next_action": "finalize",
            },
        })

        with self.assertRaisesRegex(ValidationError, "finalization_confirmation_mismatch"):
            self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Retain for user review.",
                "confirmation": f"finalize:{run_id}:1:{'a' * 64}",
            })

        self.assertFalse((self.output_root / "runs" / run_id / "final.png").exists())

    def test_intermediate_cleanup_lifecycle_prunes_references_and_completed_retry(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        arguments = self.generate_arguments(run_id)
        self.engine.generate_round(arguments)
        run_root = self.output_root / "runs" / run_id

        with self.assertRaises(AssetEngineError) as raised:
            self.engine.cleanup_run({"run_id": run_id, "scope": "intermediates", "confirmation": run_id})
        self.assertEqual(raised.exception.code, "run_not_finalized")
        self.assertTrue((run_root / "round-01.png").is_file())

        reviewed = self.review(run_id, 1)
        self.engine.finalize_run({
            "run_id": run_id,
            "round_number": 1,
            "summary": "Selected final.",
            "confirmation": reviewed["finalization_candidate"]["confirmation"],
        })
        self.engine.cleanup_run({"run_id": run_id, "scope": "intermediates", "confirmation": run_id})

        cleaned = self.engine.get_run({"run_id": run_id})
        self.assertEqual(cleaned["state"], "finalized")
        self.assertIn("intermediates_cleaned_at", cleaned)
        self.assertEqual(cleaned["final"]["image"]["path"], "final.png")
        self.assertTrue((run_root / "final.png").is_file())
        self.assertFalse((run_root / "round-01.png").exists())
        self.assertFalse((run_root / "round-01-preview.jpg").exists())
        self.assertNotIn("image", cleaned["rounds"][0])
        self.assertNotIn("preview", cleaned["rounds"][0])
        self.assertNotIn("path", cleaned["rounds"][0]["backend_result"])
        self.assertNotIn("image", cleaned["attempts"][0])
        self.assertNotIn("path", cleaned["attempts"][0]["backend_result"])

        calls_before_retry = len(self.runner.calls)
        with self.assertRaises(AssetEngineError) as retry:
            self.engine.generate_round(arguments)
        self.assertEqual(retry.exception.code, "run_artifacts_cleaned")
        self.assertEqual(len(self.runner.calls), calls_before_retry)
        self.assertEqual(self.engine.get_run({"run_id": run_id})["final"]["path"], "final.png")

    def test_ineligible_nominated_round_stays_reviewed_before_budget_is_exhausted(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        self.review(run_id, 1, hard_failures=["missing_subject"])

        with self.assertRaisesRegex(ValidationError, "finalization_confirmation_mismatch"):
            self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "User nominated an ineligible draft.",
                "confirmation": f"finalize:{run_id}:1:{'a' * 64}",
            })

        recovered = self.engine.get_run({"run_id": run_id})
        self.assertEqual(recovered["state"], "reviewed")
        self.assertEqual(
            recovered["recoverable_next_actions"],
            ["generate_round:refine", "generate_round:explore"],
        )

    def test_finalize_requires_strict_round_number_before_publication(self) -> None:
        cases = (
            ({}, "missing_argument"),
            ({"round_number": True}, "invalid_argument_type"),
            ({"round_number": "1"}, "invalid_argument_type"),
            ({"round_number": 0}, "invalid_round_number"),
            ({"round_number": 4}, "invalid_round_number"),
        )
        for change, expected_code in cases:
            with self.subTest(change=change):
                started = self.start()
                run_id = started["run_id"]
                self.engine.generate_round(self.generate_arguments(run_id, key=f"initial-{run_id}"))
                self.review(run_id, 1)
                arguments = {"run_id": run_id, "summary": "Invalid nomination.", **change}

                with self.assertRaises(ValidationError) as raised:
                    self.engine.finalize_run(arguments)

                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(self.engine.get_run({"run_id": run_id})["state"], "reviewed")
                self.assertFalse((self.output_root / "runs" / run_id / "final.png").exists())

    def test_unreviewed_or_nonexistent_nominated_round_is_rejected_before_publication(self) -> None:
        for case in ("unreviewed", "nonexistent"):
            with self.subTest(case=case):
                started = self.start()
                run_id = started["run_id"]
                self.engine.generate_round(self.generate_arguments(run_id, key=f"initial-{case}"))
                if case == "nonexistent":
                    self.review(run_id, 1)
                nominated_round = 1 if case == "unreviewed" else 2

                with self.assertRaises(AssetEngineError) as raised:
                    self.engine.finalize_run({
                        "run_id": run_id,
                        "round_number": nominated_round,
                        "summary": "Invalid nominated round.",
                        "confirmation": f"finalize:{run_id}:{nominated_round}:{'a' * 64}",
                    })

                self.assertEqual(raised.exception.code, "finalization_confirmation_mismatch")
                run_root = self.output_root / "runs" / run_id
                self.assertFalse((run_root / "final.png").exists())
                self.assertFalse((run_root / "final.pending.png").exists())

    def test_invalid_final_summary_does_not_publish_an_artifact(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        reviewed = self.review(run_id, 1)
        confirmation = reviewed["finalization_candidate"]["confirmation"]
        with self.assertRaises(ValidationError) as raised:
            self.engine.finalize_run({"run_id": run_id, "round_number": 1, "summary": " "})
        self.assertEqual(raised.exception.code, "invalid_final_summary")
        self.assertFalse((self.output_root / "runs" / run_id / "final.png").exists())
        self.assertEqual(self.engine.get_run({"run_id": run_id})["state"], "reviewed")

    def test_active_generation_prevents_final_publication_without_pending_leak(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        reviewed = self.review(run_id, 1)
        confirmation = reviewed["finalization_candidate"]["confirmation"]
        active = self.engine.store.begin_attempt(run_id, "refine-live-finalize", {
            "action": "refine",
            "seed": 42,
            "plan": {"positive_prompt": "active refinement"},
            "change_summary": "Hold finalization while refining.",
        })
        run_root = self.output_root / "runs" / run_id
        try:
            with self.assertRaises(AssetEngineError) as raised:
                self.engine.finalize_run({
                    "run_id": run_id,
                    "round_number": 1,
                    "summary": "Must wait.",
                    "confirmation": confirmation,
                })
            self.assertEqual(raised.exception.code, "run_busy")
            self.assertFalse((run_root / "final.png").exists())
            self.assertFalse((run_root / "final.pending.png").exists())
        finally:
            self.engine.store.fail_attempt(active, {"code": "cancelled", "message": "cleanup"})

    def test_latest_generated_round_must_be_reviewed_before_selecting_earlier_round(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        reviewed = self.review(run_id, 1)
        confirmation = reviewed["finalization_candidate"]["confirmation"]
        self.engine.generate_round(self.generate_arguments(run_id, key="refine-unreviewed", action="refine"))
        run_root = self.output_root / "runs" / run_id

        with self.assertRaises(AssetEngineError) as raised:
            self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Round one only.",
                "confirmation": confirmation,
            })
        self.assertEqual(raised.exception.code, "round_requires_review")
        self.assertFalse((run_root / "final.png").exists())
        self.assertFalse((run_root / "final.pending.png").exists())

    def test_generation_completing_before_final_lock_rejects_preliminary_selection(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        reviewed = self.review(run_id, 1)
        confirmation = reviewed["finalization_candidate"]["confirmation"]
        run_root = self.output_root / "runs" / run_id
        original_finalize = getattr(self.engine.store, "finalize_round_published", None)

        def complete_generation_then_finalize(*args: object, **kwargs: object) -> dict[str, object]:
            refine = self.engine.store.begin_attempt(run_id, "refine-before-final-lock", {
                "action": "refine",
                "seed": 42,
                "plan": {"positive_prompt": "completed before final lock"},
                "change_summary": "Complete refinement before finalization.",
            })
            self.engine.store.complete_attempt(refine, {"image": {"path": "round-02.png"}})
            return original_finalize(*args, **kwargs)

        with patch.object(
            self.engine.store,
            "finalize_round_published",
            create=True,
            side_effect=complete_generation_then_finalize,
        ) as finalize_call:
            with self.assertRaises(AssetEngineError) as raised:
                self.engine.finalize_run({
                    "run_id": run_id,
                    "round_number": 1,
                    "summary": "Raced selection.",
                    "confirmation": confirmation,
                })
        self.assertEqual(finalize_call.call_count, 1)
        self.assertEqual(raised.exception.code, "round_requires_review")
        self.assertFalse((run_root / "final.png").exists())
        self.assertFalse((run_root / "final.pending.png").exists())

    def test_final_publication_rolls_back_engine_publisher_and_manifest_failures(self) -> None:
        for failure in ("publisher", "manifest"):
            with self.subTest(failure=failure):
                with tempfile.TemporaryDirectory() as directory:
                    output_root = Path(directory) / "output"
                    engine = AssetRunEngine(
                        self.registry,
                        RunStore(output_root),
                        FakeBackendRunner(),
                        lambda: self.capabilities,
                        catalog=self.catalog,
                        router=self.router,
                        compilers=self.compilers,
                    )
                    started = engine.start_run(self.start_arguments())
                    run_id = started["run_id"]
                    engine.generate_round(self.generate_arguments(run_id))
                    rubric = engine.get_run({"run_id": run_id})["request"]["merged_profile"]["rubric"]
                    reviewed = engine.record_review({
                        "run_id": run_id,
                        "round_number": 1,
                        "review": {
                            "scores": {name: 4 for name in rubric},
                            "hard_failures": [],
                            "critique": "Reviewed.",
                            "constraint_results": {
                                "width": {"status": "pass", "observation": "Width matches."},
                                "height": {"status": "pass", "observation": "Height matches."},
                            },
                            "visual_checks": visual_checks(),
                            "next_action": "finalize",
                        },
                    })
                    confirmation = reviewed["finalization_candidate"]["confirmation"]
                    run_root = output_root / "runs" / run_id
                    if failure == "publisher":
                        (run_root / "final.png").write_bytes(b"prior-untracked-final")
                        context = patch("local_gpu_imagegen.engine.os.replace", side_effect=OSError("publish failed"))
                    else:
                        context = patch("local_gpu_imagegen.run_store.atomic_write_json", side_effect=OSError("manifest failed"))
                    with context:
                        with self.assertRaises(OSError):
                            engine.finalize_run({
                                "run_id": run_id,
                                "round_number": 1,
                                "summary": "Transactional final.",
                                "confirmation": confirmation,
                            })
                    if failure == "publisher":
                        self.assertEqual((run_root / "final.png").read_bytes(), b"prior-untracked-final")
                    else:
                        self.assertFalse((run_root / "final.png").exists())
                    self.assertFalse((run_root / "final.pending.png").exists())
                    self.assertEqual(engine.get_run({"run_id": run_id})["state"], "reviewed")

    def test_concurrent_engine_finalizer_cannot_delete_winner_pending_file(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        reviewed = self.review(run_id, 1)
        confirmation = reviewed["finalization_candidate"]["confirmation"]
        copied = threading.Event()
        continue_winner = threading.Event()
        winner_results: list[dict[str, object]] = []
        winner_errors: list[BaseException] = []
        original_copy = shutil.copyfile

        def paused_copy(source: Path, destination: Path) -> str:
            result = original_copy(source, destination)
            copied.set()
            continue_winner.wait(timeout=5)
            return result

        def finalize_winner() -> None:
            try:
                winner_results.append(self.engine.finalize_run({
                    "run_id": run_id,
                    "round_number": 1,
                    "summary": "Winner.",
                    "confirmation": confirmation,
                }))
            except BaseException as error:
                winner_errors.append(error)

        with patch("local_gpu_imagegen.engine.shutil.copyfile", side_effect=paused_copy):
            winner = threading.Thread(target=finalize_winner)
            winner.start()
            self.assertTrue(copied.wait(timeout=5))
            try:
                with self.assertRaises(AssetEngineError) as raised:
                    self.engine.finalize_run({
                        "run_id": run_id,
                        "round_number": 1,
                        "summary": "Loser.",
                        "confirmation": confirmation,
                    })
                self.assertEqual(raised.exception.code, "run_busy")
            finally:
                continue_winner.set()
            winner.join(timeout=5)
        self.assertFalse(winner.is_alive())
        self.assertEqual(winner_errors, [])
        self.assertEqual(len(winner_results), 1)
        run_root = self.output_root / "runs" / run_id
        self.assertTrue((run_root / "final.png").is_file())
        self.assertFalse((run_root / "final.pending.png").exists())

    def test_post_commit_cleanup_failure_returns_warning_and_retains_backup(self) -> None:
        started = self.start()
        run_id = started["run_id"]
        self.engine.generate_round(self.generate_arguments(run_id))
        reviewed = self.review(run_id, 1)
        run_root = self.output_root / "runs" / run_id
        (run_root / "final.png").write_bytes(b"prior-final-for-diagnosis")
        original_unlink = Path.unlink

        def fail_committed_backup_cleanup(path: Path, *args: object, **kwargs: object) -> None:
            if path.name.startswith(".final.rollback.") and path.exists():
                raise OSError("cleanup failed")
            original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=fail_committed_backup_cleanup):
            finalized = self.engine.finalize_run({
                "run_id": run_id,
                "round_number": 1,
                "summary": "Committed despite cleanup.",
                "confirmation": reviewed["finalization_candidate"]["confirmation"],
            })

        self.assertEqual(finalized["state"], "finalized")
        self.assertIn("finalize_cleanup_failed", finalized["warnings"])
        self.assertEqual(finalized["finalize_cleanup_warning"]["code"], "finalize_cleanup_failed")
        backups = list(run_root.glob(".final.rollback.*.png"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"prior-final-for-diagnosis")
        self.assertEqual(self.engine.store.get(run_id)["state"], "finalized")

    def test_cleanup_requires_exact_confirmation(self) -> None:
        started = self.start()
        with self.assertRaises(AssetEngineError) as raised:
            self.engine.cleanup_run({"run_id": started["run_id"], "scope": "all", "confirmation": "wrong"})
        self.assertEqual(raised.exception.code, "cleanup_confirmation_mismatch")
        cleaned = self.engine.cleanup_run({
            "run_id": started["run_id"],
            "scope": "all",
            "confirmation": started["run_id"],
        })
        self.assertEqual(cleaned, {"ok": True, "run_id": started["run_id"], "scope": "all"})
        self.assertFalse((self.output_root / "runs" / started["run_id"]).exists())


if __name__ == "__main__":
    unittest.main()
