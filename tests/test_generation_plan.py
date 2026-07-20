from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.generation_plan import validate_generation_plan  # noqa: E402


class GenerationPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_request = {
            "profile": "standalone-illustration",
            "style": None,
            "intent": "A sailor looking over a calm sea.",
            "constraints": {"aspect_ratio": "1:1"},
            "model_choice": "local-model",
            "max_rounds": 2,
            "upscale_policy": "auto",
            "backend": "auto",
            "available_backends": ["webui"],
            "merged_profile": {"refine_mutable": ["denoise_strength"], "explore_mutable": ["seed"]},
        }
        self.plan = {
            "profile": "standalone-illustration",
            "style": None,
            "intent": "A sailor looking over a calm sea.",
            "positive_prompt": "a sailor looking over a calm sea, illustration",
            "negative_prompt": "",
            "constraints": {"aspect_ratio": "1:1"},
            "model_choice": "local-model",
            "backend": "webui",
            "parameters": {},
            "max_rounds": 2,
            "upscale_policy": "auto",
        }

    def test_accepts_complete_plan_matching_confirmed_run(self) -> None:
        validated = validate_generation_plan(self.plan, self.run_request, "initial")
        self.assertEqual(validated["positive_prompt"], self.plan["positive_prompt"])

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

    def test_auto_backend_requires_an_advertised_resolution(self) -> None:
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
            "upscale_policy", "backend", "available_backends",
        )
        for field in required:
            with self.subTest(field=field):
                incomplete = {key: value for key, value in self.run_request.items() if key != field}
                with self.assertRaisesRegex(ValidationError, "invalid_run_request"):
                    validate_generation_plan(self.plan, incomplete, "initial")


if __name__ == "__main__":
    unittest.main()
