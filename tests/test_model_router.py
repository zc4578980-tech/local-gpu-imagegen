from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ConflictError, ValidationError  # noqa: E402
from local_gpu_imagegen.model_router import CapabilityRouter  # noqa: E402
from local_gpu_imagegen.prompt_compilers import PromptCompilerRegistry  # noqa: E402
from local_gpu_imagegen.regional_layout import REGIONAL_TEMPLATE_ID  # noqa: E402
from local_gpu_imagegen.two_stage_layout import (  # noqa: E402
    TWO_STAGE_LAYOUT_MODE,
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
)


WORKFLOW_SHA256 = "d" * 64
BUNDLE_SHA256 = "e" * 64


class MutableClock:
    def __init__(self, value: float = 1000) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def model(model_id: str, evidence: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": model_id,
        "backend": "webui",
        "endpoint_identity": "endpoint:webui",
        "backend_model_id": f"{model_id}.safetensors",
        "identity_token": "model:" + (model_id[-1] * 64),
        "identity_strength": "cryptographic",
        "sha256": model_id[-1] * 64,
        "model_family": "unknown",
        "prompt_compiler_id": "natural-v1",
        "capabilities": {
            "operations": ["txt2img", "inpaint"],
            "minimum_dimension": 256,
            "maximum_dimension": 1536,
            "minimum_vram_gb": 6,
            "negative_prompt": "supported",
        },
        "affinity": ["anime", "illustration"],
        "evidence_level": evidence,
        "evidence_operations": ["txt2img", "inpaint"],
        "preference": 0,
        "limitations": [],
        "recommended": {
            "resolution": {"width": 768, "height": 512},
            "steps": 20,
            "guidance": 7.0,
            "sampler": "euler",
            "scheduler": "normal",
        },
        "workflow_template_id": None,
        "workflow_template_version": None,
        "component_bundle": None,
        "component_bundle_sha256": None,
        "control_sha256": None,
    }
    value.update(changes)
    return value


def requirements(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "authorization_scope": "private",
        "operation": "txt2img",
        "profile": "standalone-illustration",
        "style": "anime",
        "width": 768,
        "height": 512,
        "affinity_tags": ["anime", "illustration"],
        "required_vram_gb": 8,
        "preferred_model_id": None,
    }
    value.update(changes)
    return value


class FakeCatalog:
    def __init__(self, models: list[dict[str, object]]) -> None:
        self.models = models
        self.reverse = False
        self.drifted = False
        self.verified: list[dict[str, object]] = []

    def list_models(self, _scope: str) -> list[dict[str, object]]:
        self.reverse = not self.reverse
        values = list(reversed(self.models)) if self.reverse else list(self.models)
        return copy.deepcopy(values)

    def verify_locked_route(self, route: dict[str, object]) -> dict[str, object]:
        self.verified.append(copy.deepcopy(route))
        if self.drifted:
            raise ConflictError("model_identity_drifted", "drifted")
        return next(item for item in self.models if item["id"] == route["model_id"])


class ModelRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.capability_calls: list[str] = []
        self.capability: dict[str, object] = {
            "mode": "copy-subject-v1",
            "available": True,
            "endpoint_identity": "endpoint:regional",
            "reason": None,
        }

        def regional_capability(mode: str) -> dict[str, object]:
            self.capability_calls.append(mode)
            return copy.deepcopy(self.capability)

        self.catalog = FakeCatalog([
            model("model-declared-d", "declared"),
            model("model-observed-o", "observed"),
            model("model-benchmarked-b", "benchmarked"),
            model("model-extra-x", "declared"),
        ])
        self.router = CapabilityRouter(
            self.catalog,
            PromptCompilerRegistry(),
            regional_capability_provider=regional_capability,
            clock=self.clock,
            ttl_seconds=300,
        )

    def test_router_hard_filters_then_returns_stable_three_maximum(self) -> None:
        first = self.router.recommend(requirements(operation="inpaint"))
        second = self.router.recommend(requirements(operation="inpaint"))

        self.assertEqual(len(first["routes"]), 3)
        self.assertEqual(
            [route["model_id"] for route in first["routes"]],
            [
                "model-benchmarked-b",
                "model-observed-o",
                "model-declared-d",
            ],
        )
        self.assertEqual(
            [route["model_id"] for route in first["routes"]],
            [route["model_id"] for route in second["routes"]],
        )
        self.assertEqual(first["routes"][0]["evidence_level"], "benchmarked")
        self.assertIn("score_components", first["routes"][0])
        self.assertEqual(self.capability_calls, [])

    @staticmethod
    def regional_layout() -> dict[str, object]:
        return {
            "mode": "copy-subject-v1",
            "copy_region": {
                "x": 0.0,
                "y": 0.0,
                "width": 0.45,
                "height": 1.0,
            },
            "subject_region": {
                "x": 0.68,
                "y": 0.0,
                "width": 0.30,
                "height": 1.0,
            },
        }

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

    def two_stage_model(self) -> dict[str, object]:
        layout = self.two_stage_layout()
        value = model(
            "model-two-stage-t",
            "observed",
            backend="comfyui",
            endpoint_identity="endpoint:regional",
            workflow_template_id=TWO_STAGE_TEMPLATE_ID,
            workflow_template_version=1,
            component_bundle={
                "schema_version": 1,
                "components": [],
                "workflow": {
                    "template_id": TWO_STAGE_TEMPLATE_ID,
                    "template_version": 1,
                    "sha256": WORKFLOW_SHA256,
                },
                "bundle_sha256": BUNDLE_SHA256,
            },
            component_bundle_sha256=BUNDLE_SHA256,
            control_sha256=build_control_identity(
                layout,
                WORKFLOW_SHA256,
                "base-subject-v1",
            ),
        )
        value["capabilities"]["two_stage_layout_modes"] = [
            TWO_STAGE_LAYOUT_MODE
        ]
        return value

    def test_regional_requirement_filters_workflow_mode_and_live_endpoint(self) -> None:
        regional = model(
            "model-regional-a",
            "observed",
            backend="comfyui",
            endpoint_identity="endpoint:regional",
            workflow_template_id="sdxl-regional-txt2img",
            workflow_template_version=1,
        )
        regional["capabilities"]["regional_layout_modes"] = [
            "copy-subject-v1"
        ]
        ordinary = model(
            "model-ordinary-b",
            "benchmarked",
            backend="comfyui",
            endpoint_identity="endpoint:regional",
            workflow_template_id="sdxl-txt2img",
            workflow_template_version=1,
        )
        self.catalog.models = [regional, ordinary]
        layout = self.regional_layout()

        result = self.router.recommend(requirements(regional_layout=layout))

        self.assertEqual(
            [item["model_id"] for item in result["routes"]],
            [regional["id"]],
        )
        self.assertEqual(self.capability_calls, ["copy-subject-v1"])
        changed = copy.deepcopy(layout)
        changed["copy_region"]["width"] = 0.40
        other = self.router.recommend(requirements(regional_layout=changed))
        self.assertNotEqual(
            result["routes"][0]["route_token"],
            other["routes"][0]["route_token"],
        )

        self.capability["endpoint_identity"] = "endpoint:other"
        mismatch = self.router.recommend(requirements(regional_layout=layout))
        self.assertEqual(mismatch["routes"], [])

    def test_unavailable_nodes_return_no_route_without_fallback(self) -> None:
        self.catalog.models = [model("model-ordinary-b", "benchmarked")]
        self.capability["available"] = False
        self.capability["reason"] = "regional_layout_unavailable"

        result = self.router.recommend(
            requirements(regional_layout=self.regional_layout())
        )

        self.assertEqual(result["routes"], [])
        self.assertEqual(result["reason"], "regional_layout_unavailable")
        self.assertEqual(self.capability_calls, ["copy-subject-v1"])

    def test_two_stage_requirement_returns_only_exact_capable_variant(self) -> None:
        two_stage = self.two_stage_model()
        ordinary = model(
            "model-ordinary-b",
            "benchmarked",
            backend="comfyui",
            endpoint_identity="endpoint:regional",
            workflow_template_id="sdxl-txt2img",
            workflow_template_version=1,
        )
        self.catalog.models = [ordinary, two_stage]
        layout = self.two_stage_layout()
        self.capability["mode"] = TWO_STAGE_LAYOUT_MODE

        result = self.router.recommend(requirements(
            width=640,
            height=320,
            two_stage_layout=layout,
        ))

        self.assertEqual(len(result["routes"]), 1)
        route = result["routes"][0]
        self.assertEqual(route["workflow_template_id"], TWO_STAGE_TEMPLATE_ID)
        self.assertEqual(route["control_sha256"], two_stage["control_sha256"])
        self.assertEqual(route["component_bundle_sha256"], BUNDLE_SHA256)
        self.assertEqual(self.capability_calls, [TWO_STAGE_LAYOUT_MODE])
        boundary = {
            key: copy.deepcopy(value)
            for key, value in route.items()
            if key not in {"route_token", "expires_at"}
        }
        encoded = json.dumps(
            boundary,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(
            route["route_token"],
            "route:" + hashlib.sha256(encoded).hexdigest(),
        )
        changed = copy.deepcopy(boundary)
        changed["control_sha256"] = "f" * 64
        self.assertNotEqual(
            route["route_token"],
            "route:" + hashlib.sha256(json.dumps(
                changed,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")).hexdigest(),
        )

    def test_two_stage_route_never_falls_back(self) -> None:
        layout = self.two_stage_layout()
        expected_control = build_control_identity(
            layout,
            WORKFLOW_SHA256,
            "base-subject-v1",
        )
        for failure in ("capability", "workflow", "control", "bundle", "endpoint"):
            with self.subTest(failure=failure):
                candidate = self.two_stage_model()
                self.capability.update({
                    "mode": TWO_STAGE_LAYOUT_MODE,
                    "available": True,
                    "endpoint_identity": "endpoint:regional",
                    "reason": None,
                })
                if failure == "capability":
                    candidate["capabilities"]["two_stage_layout_modes"] = []
                elif failure == "workflow":
                    candidate["workflow_template_id"] = REGIONAL_TEMPLATE_ID
                elif failure == "control":
                    candidate["control_sha256"] = "f" * 64
                elif failure == "bundle":
                    candidate["component_bundle_sha256"] = "f" * 64
                else:
                    candidate["endpoint_identity"] = "endpoint:other"
                self.catalog.models = [
                    candidate,
                    model("model-fallback-f", "benchmarked"),
                ]

                result = self.router.recommend(requirements(
                    width=640,
                    height=320,
                    two_stage_layout=layout,
                ))

                self.assertEqual(result["routes"], [])
                self.assertNotEqual(candidate.get("control_sha256"), None)
                if failure != "control":
                    self.assertEqual(candidate["control_sha256"], expected_control)

    def test_layout_requirements_are_mutually_exclusive_and_ordinary_is_standard_only(self) -> None:
        regional = model(
            "model-regional-r",
            "observed",
            backend="comfyui",
            endpoint_identity="endpoint:regional",
            workflow_template_id=REGIONAL_TEMPLATE_ID,
            workflow_template_version=1,
        )
        regional["capabilities"]["regional_layout_modes"] = ["copy-subject-v1"]
        two_stage = self.two_stage_model()
        ordinary = model("model-ordinary-o", "declared")
        self.catalog.models = [regional, two_stage, ordinary]

        self.assertEqual(
            [route["model_id"] for route in self.router.recommend(requirements())["routes"]],
            [ordinary["id"]],
        )
        with self.assertRaisesRegex(ValidationError, "invalid_route_requirements"):
            self.router.recommend(requirements(
                regional_layout=self.regional_layout(),
                two_stage_layout=self.two_stage_layout(),
            ))

    def test_router_returns_no_route_instead_of_weakening_hard_requirement(self) -> None:
        result = self.router.recommend(requirements(
            operation="inpaint",
            authorization_scope="public_evidence",
            required_vram_gb=4,
        ))

        self.assertEqual(result["routes"], [])
        self.assertEqual(result["reason"], "no_eligible_model")

    def test_route_exposes_exact_identity_compiler_settings_and_binding_warning(self) -> None:
        private = model(
            "model-private-p",
            "observed",
            identity_strength="backend_binding",
            sha256=None,
        )
        self.catalog.models = [private]

        route = self.router.recommend(requirements())["routes"][0]

        self.assertEqual(route["prompt_compiler_id"], "natural-v1")
        self.assertEqual(route["prompt_compiler_version"], 1)
        self.assertEqual(route["recommended_settings"]["steps"], 20)
        self.assertIn("binding", route["identity_warning"].lower())
        self.assertRegex(route["route_token"], r"^route:[0-9a-f]{64}$")
        self.assertNotIn("control_sha256", route)

    def test_route_token_freezes_complete_normalized_requirements(self) -> None:
        first = self.router.recommend(requirements(required_vram_gb=8))["routes"][0]
        second = self.router.recommend(requirements(required_vram_gb=12))["routes"][0]

        self.assertEqual(first["requirements"]["required_vram_gb"], 8)
        self.assertEqual(second["requirements"]["required_vram_gb"], 12)
        self.assertNotEqual(first["route_token"], second["route_token"])

    def test_route_token_and_public_filter_bind_component_bundle(self) -> None:
        bundle = {
            "schema_version": 1,
            "components": [],
            "workflow": {},
            "bundle_sha256": "f" * 64,
        }
        self.catalog.models = [model(
            "model-comfy-c",
            "observed",
            backend="comfyui",
            workflow_template_id="z-image-turbo-txt2img",
            workflow_template_version=1,
            component_bundle=bundle,
            component_bundle_sha256="f" * 64,
        )]

        first = self.router.recommend(requirements(authorization_scope="public_evidence"))["routes"][0]
        self.catalog.models[0]["component_bundle_sha256"] = "e" * 64
        second = self.router.recommend(requirements(authorization_scope="public_evidence"))["routes"][0]

        self.assertEqual(first["component_bundle"], bundle)
        self.assertEqual(first["component_bundle_sha256"], "f" * 64)
        self.assertNotEqual(first["route_token"], second["route_token"])

        self.catalog.models[0]["component_bundle"] = None
        self.assertEqual(
            self.router.recommend(requirements(authorization_scope="public_evidence"))["routes"],
            [],
        )

    def test_confirm_is_exact_one_time_and_revalidates_current_catalog(self) -> None:
        route = self.router.recommend(requirements())["routes"][0]

        with self.assertRaisesRegex(ConflictError, "route_confirmation_expired"):
            self.router.confirm(route["route_token"], "wrong-model")
        confirmed = self.router.confirm(route["route_token"], route["model_id"])
        self.assertEqual(confirmed["route_token"], route["route_token"])
        self.assertEqual(len(self.catalog.verified), 1)
        with self.assertRaisesRegex(ConflictError, "route_confirmation_expired"):
            self.router.confirm(route["route_token"], route["model_id"])

    def test_expired_or_drifted_route_never_confirms(self) -> None:
        expired = self.router.recommend(requirements())["routes"][0]
        self.clock.value = expired["expires_at"] + 1
        with self.assertRaisesRegex(ConflictError, "route_confirmation_expired"):
            self.router.confirm(expired["route_token"], expired["model_id"])

        self.clock.value = 2000
        drifted = self.router.recommend(requirements())["routes"][0]
        self.catalog.drifted = True
        with self.assertRaisesRegex(ConflictError, "model_identity_drifted"):
            self.router.confirm(drifted["route_token"], drifted["model_id"])

    def test_invalid_requirements_fail_before_catalog_access(self) -> None:
        invalid = (
            requirements(width=200),
            requirements(operation="video"),
            requirements(affinity_tags=["anime", "anime"]),
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError,
                "invalid_route_requirements",
            ):
                self.router.recommend(value)


if __name__ == "__main__":
    unittest.main()
