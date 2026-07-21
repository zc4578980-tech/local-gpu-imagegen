from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.generation_plan import (  # noqa: E402
    validate_confirmed_run_request,
    validate_generation_plan,
)


class GenerationPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_request = {
            "profile": "standalone-illustration",
            "style": None,
            "intent": "A sailor looking over a calm sea.",
            "constraints": {"aspect_ratio": "1:1"},
            "model_choice": "local:test-model",
            "max_rounds": 2,
            "upscale_policy": "off",
            "backend": "comfyui",
            "available_backends": ["comfyui"],
            "authorization_scope": "private",
            "route_token": "route:test",
            "endpoint_identity": "endpoint:test",
            "model_identity_token": "model:test",
            "identity_strength": "cryptographic",
            "workflow_template_id": "sd15-txt2img-v1",
            "workflow_template_version": 1,
            "prompt_compiler_id": "sd15-tags-v1",
            "prompt_compiler_version": 1,
            "route": {
                "authorization_scope": "private",
                "route_token": "route:test",
                "model_id": "local:test-model",
                "backend": "comfyui",
                "endpoint_identity": "endpoint:test",
                "identity_token": "model:test",
                "identity_strength": "cryptographic",
                "workflow_template_id": "sd15-txt2img-v1",
                "workflow_template_version": 1,
                "prompt_compiler_id": "sd15-tags-v1",
                "prompt_compiler_version": 1,
            },
            "merged_profile": {"refine_mutable": ["denoise_strength"], "explore_mutable": ["seed"]},
        }
        self.plan = {
            "profile": "standalone-illustration",
            "style": None,
            "intent": "A sailor looking over a calm sea.",
            "positive_prompt": "a sailor looking over a calm sea, illustration",
            "negative_prompt": "",
            "constraints": {"aspect_ratio": "1:1"},
            "model_choice": "local:test-model",
            "backend": "comfyui",
            "authorization_scope": "private",
            "route_token": "route:test",
            "endpoint_identity": "endpoint:test",
            "model_identity_token": "model:test",
            "identity_strength": "cryptographic",
            "workflow_template_id": "sd15-txt2img-v1",
            "workflow_template_version": 1,
            "prompt_compiler_id": "sd15-tags-v1",
            "prompt_compiler_version": 1,
            "parameters": {},
            "max_rounds": 2,
            "upscale_policy": "off",
        }

    def test_accepts_complete_plan_matching_confirmed_run(self) -> None:
        validated = validate_generation_plan(self.plan, self.run_request, "initial")
        self.assertEqual(validated["positive_prompt"], self.plan["positive_prompt"])
        self.assertEqual(validated["model_choice"], "local:test-model")
        self.assertEqual(validated["upscale_policy"], "off")

    def test_rejects_nested_mode_that_disagrees_with_authoritative_txt2img(self) -> None:
        for nested_mode in ("img2img", "inpaint"):
            with self.subTest(nested_mode=nested_mode):
                changed = {**self.plan, "parameters": {"mode": nested_mode}}
                with self.assertRaisesRegex(ValidationError, "edit_mode_mismatch"):
                    validate_generation_plan(changed, self.run_request, "initial")

    def test_rejects_profile_or_budget_drift(self) -> None:
        with self.assertRaisesRegex(ValidationError, "generation_plan_mismatch"):
            validate_generation_plan({**self.plan, "max_rounds": 3}, self.run_request, "refine")

    def test_rejects_dropped_user_constraint(self) -> None:
        changed = {**self.plan, "constraints": {}}
        with self.assertRaisesRegex(ValidationError, "generation_plan_mismatch"):
            validate_generation_plan(changed, self.run_request, "refine")

    def test_rejects_parameter_not_mutable_for_action(self) -> None:
        changed = {**self.plan, "parameters": {"seed": 99}}
        with self.assertRaisesRegex(ValidationError, "parameter_not_allowed"):
            validate_generation_plan(changed, self.run_request, "refine")

    def test_rejects_invalid_backend_type(self) -> None:
        with self.assertRaisesRegex(ValidationError, "invalid_backend"):
            validate_generation_plan({**self.plan, "backend": []}, self.run_request, "initial")

    def test_confirmed_backend_must_remain_advertised(self) -> None:
        unavailable = {**self.run_request, "available_backends": []}
        with self.assertRaisesRegex(ValidationError, "invalid_backend"):
            validate_generation_plan(self.plan, unavailable, "initial")

    def test_returns_a_deep_copy(self) -> None:
        validated = validate_generation_plan(self.plan, self.run_request, "initial")
        validated["constraints"]["aspect_ratio"] = "16:9"
        self.assertEqual(self.plan["constraints"]["aspect_ratio"], "1:1")

    def test_rejects_incomplete_confirmed_run_request(self) -> None:
        required = (
            "profile", "style", "intent", "constraints", "model_choice", "max_rounds",
            "upscale_policy", "backend", "available_backends", "authorization_scope",
            "route_token", "route",
        )
        for field in required:
            with self.subTest(field=field):
                incomplete = {key: value for key, value in self.run_request.items() if key != field}
                with self.assertRaisesRegex(ValidationError, "invalid_run_request"):
                    validate_generation_plan(self.plan, incomplete, "initial")

    def test_shared_confirmed_request_validator_rejects_semantic_invalidity(self) -> None:
        invalid = (
            {**self.run_request, "intent": "   "},
            {**self.run_request, "model_choice": 42},
            {**self.run_request, "backend": "auto"},
            {**self.run_request, "upscale_policy": "sometimes"},
            {**self.run_request, "available_backends": ["unknown"]},
        )
        for request in invalid:
            with self.subTest(request=request):
                with self.assertRaises(ValidationError):
                    validate_confirmed_run_request(request)


if __name__ == "__main__":
    unittest.main()
