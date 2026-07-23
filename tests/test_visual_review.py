from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.two_stage_layout import TWO_STAGE_TEMPLATE_ID  # noqa: E402
from local_gpu_imagegen.visual_review import (
    finalization_candidate,
    require_finalization_confirmation,
    review_is_eligible,
    validate_visual_checks,
    visual_checks_pass,
)  # noqa: E402


def passing_checks(*, prominent_human: bool = True) -> dict[str, object]:
    anatomy_status = "pass" if prominent_human else "not_applicable"
    anatomy_observation = (
        "Independent anatomy is visible."
        if prominent_human
        else "No prominent human is present."
    )
    return {
        "full_resolution_inspected": True,
        "prominent_human": prominent_human,
        "limb_separation": {
            "status": anatomy_status,
            "observation": anatomy_observation,
        },
        "feet_and_contact": {
            "status": anatomy_status,
            "observation": anatomy_observation,
        },
        "hands_and_held_objects": {
            "status": anatomy_status,
            "observation": anatomy_observation,
        },
        "text_and_watermarks": {
            "status": "pass",
            "observation": "No text or watermark is visible.",
        },
    }


def passing_stage_checks() -> dict[str, object]:
    return {
        "base_copy_space": {"status": "pass", "observation": "Left copy space is usable."},
        "base_subject_absent": {"status": "pass", "observation": "The subject is absent from base."},
        "final_subject_inside_mask": {"status": "pass", "observation": "The subject stays inside the mask."},
        "final_safe_margins": {"status": "pass", "observation": "Safe margins remain visible."},
        "final_forbidden_content": {"status": "pass", "observation": "Forbidden content is absent."},
        "feather_transition": {"status": "pass", "observation": "The transition is coherent."},
        "pixel_preservation": {"status": "pass", "observation": "Machine report records zero mismatches."},
    }


def eligible_manifest(
    *,
    image_sha256: str = "a" * 64,
    visual_checks: dict[str, object] | None = None,
    two_stage: bool = False,
) -> dict[str, object]:
    review: dict[str, object] = {
        "round_number": 1,
        "scores": {"anatomy": 4, "style": 2},
        "hard_failures": [],
        "critique": "Reviewed at full resolution.",
        "constraint_results": {},
        "next_action": "finalize",
    }
    if visual_checks is not None:
        review["visual_checks"] = copy.deepcopy(visual_checks)
    manifest = {
        "run_id": "run-1",
        "request": {
            "merged_profile": {
                "rubric": {
                    "anatomy": {"critical": True},
                    "style": {"critical": False},
                },
            },
        },
        "rounds": [{
            "round_number": 1,
            "image": {
                "path": "round-01.png",
                "sha256": image_sha256,
                "width": 768,
                "height": 432,
            },
        }],
        "reviews": [review],
    }
    if two_stage:
        manifest["request"]["workflow_template_id"] = TWO_STAGE_TEMPLATE_ID
        manifest["rounds"][0]["pixel_preservation"] = {
            "checked_pixels": 100,
            "mismatched_pixels": 0,
            "copy_mismatched_pixels": 0,
        }
        review["stage_checks"] = passing_stage_checks()
    return manifest


class VisualReviewTests(unittest.TestCase):
    def test_two_stage_eligibility_requires_every_stage_check_to_pass(self) -> None:
        manifest = eligible_manifest(visual_checks=passing_checks(), two_stage=True)
        self.assertTrue(review_is_eligible(manifest, manifest["reviews"][0]))

        for name in passing_stage_checks():
            changed = copy.deepcopy(manifest)
            changed["reviews"][0]["stage_checks"][name]["status"] = "uncertain"
            with self.subTest(name=name):
                self.assertFalse(review_is_eligible(changed, changed["reviews"][0]))

    def test_two_stage_eligibility_requires_recorded_zero_pixel_mismatches(self) -> None:
        manifest = eligible_manifest(visual_checks=passing_checks(), two_stage=True)
        manifest["rounds"][0]["pixel_preservation"]["mismatched_pixels"] = 1

        self.assertFalse(review_is_eligible(manifest, manifest["reviews"][0]))

    def test_visual_checks_require_exact_fields_and_full_resolution_true(self) -> None:
        cases = ({}, {**passing_checks(), "full_resolution_inspected": False})
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_visual_checks(value)

    def test_visual_checks_reject_unknown_status_empty_observation_and_extra_field(self) -> None:
        invalid_status = passing_checks()
        invalid_status["limb_separation"] = {
            "status": "skipped",
            "observation": "Not inspected.",
        }
        empty_observation = passing_checks()
        empty_observation["feet_and_contact"] = {
            "status": "pass",
            "observation": " ",
        }
        extra_field = {**passing_checks(), "face_quality": {"status": "pass", "observation": "Clear."}}

        for value in (invalid_status, empty_observation, extra_field):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_visual_checks(value)

    def test_human_anatomy_cannot_be_not_applicable(self) -> None:
        checks = passing_checks()
        checks["feet_and_contact"] = {
            "status": "not_applicable",
            "observation": "Feet are hidden.",
        }

        with self.assertRaisesRegex(ValidationError, "inconsistent_visual_checks"):
            validate_visual_checks(checks)

    def test_non_human_anatomy_must_be_not_applicable(self) -> None:
        checks = passing_checks(prominent_human=False)
        checks["limb_separation"] = {
            "status": "pass",
            "observation": "Not relevant.",
        }

        with self.assertRaisesRegex(ValidationError, "inconsistent_visual_checks"):
            validate_visual_checks(checks)

    def test_text_and_watermarks_cannot_be_not_applicable(self) -> None:
        checks = passing_checks(prominent_human=False)
        checks["text_and_watermarks"] = {
            "status": "not_applicable",
            "observation": "Not checked.",
        }

        with self.assertRaisesRegex(ValidationError, "inconsistent_visual_checks"):
            validate_visual_checks(checks)

    def test_fail_and_uncertain_are_fail_closed(self) -> None:
        for status in ("fail", "uncertain"):
            checks = passing_checks()
            checks["limb_separation"] = {
                "status": status,
                "observation": "Lower legs merge.",
            }

            with self.subTest(status=status):
                self.assertFalse(visual_checks_pass(checks))

    def test_non_human_passes_with_explicit_anatomy_not_applicable(self) -> None:
        self.assertTrue(visual_checks_pass(passing_checks(prominent_human=False)))

    def test_candidate_binds_run_round_and_retained_sha256(self) -> None:
        manifest = eligible_manifest(visual_checks=passing_checks())

        candidate = finalization_candidate(manifest, 1)

        self.assertEqual(candidate, {
            "run_id": "run-1",
            "round_number": 1,
            "image_sha256": "a" * 64,
            "confirmation": f"finalize:run-1:1:{'a' * 64}",
            "quality_status": "candidate",
        })

    def test_missing_legacy_checks_fail_closed(self) -> None:
        manifest = eligible_manifest(visual_checks=None)

        self.assertFalse(review_is_eligible(manifest, manifest["reviews"][0]))
        self.assertIsNone(finalization_candidate(manifest, 1))
        with self.assertRaisesRegex(ValidationError, "finalization_confirmation_mismatch"):
            require_finalization_confirmation(
                manifest,
                1,
                f"finalize:run-1:1:{'a' * 64}",
            )

    def test_candidate_requires_finalize_action_and_all_other_eligibility_rules(self) -> None:
        cases = []

        hard_failure = eligible_manifest(visual_checks=passing_checks())
        hard_failure["reviews"][0]["hard_failures"] = ["severe_anatomy"]
        cases.append(hard_failure)

        low_critical = eligible_manifest(visual_checks=passing_checks())
        low_critical["reviews"][0]["scores"]["anatomy"] = 2
        cases.append(low_critical)

        refining = eligible_manifest(visual_checks=passing_checks())
        refining["reviews"][0]["next_action"] = "refine"
        cases.append(refining)

        preservation_uncertain = eligible_manifest(visual_checks=passing_checks())
        preservation_uncertain["reviews"][0]["preservation_results"] = [{
            "target": "subject",
            "status": "uncertain",
            "observation": "Identity is unclear.",
        }]
        cases.append(preservation_uncertain)

        for manifest in cases:
            with self.subTest(review=manifest["reviews"][0]):
                self.assertIsNone(finalization_candidate(manifest, 1))

    def test_wrong_confirmation_is_rejected(self) -> None:
        manifest = eligible_manifest(visual_checks=passing_checks())

        with self.assertRaisesRegex(ValidationError, "finalization_confirmation_mismatch"):
            require_finalization_confirmation(manifest, 1, "finalize:run-1:2:" + "a" * 64)


if __name__ == "__main__":
    unittest.main()
