from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.regional_layout import (  # noqa: E402
    LAYOUT_MODE,
    REGIONAL_TEMPLATE_ID,
    validate_regional_conditioning,
    validate_regional_layout,
    validate_regional_node_info,
)


class RegionalLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = {
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
        self.conditioning = {
            "copy_prompt": "dark empty low-detail copy space",
            "copy_strength": 1.15,
            "subject_prompt": "one complete brass telescope on a tripod",
            "subject_strength": 1.25,
        }

    def test_exports_the_only_supported_mode_and_template(self) -> None:
        self.assertEqual(LAYOUT_MODE, "copy-subject-v1")
        self.assertEqual(REGIONAL_TEMPLATE_ID, "sdxl-regional-txt2img")

    def test_valid_contract_is_trimmed_and_deep_copied(self) -> None:
        conditioning = {
            **self.conditioning,
            "copy_prompt": "  empty copy space  ",
        }

        layout = validate_regional_layout(self.layout)
        normalized = validate_regional_conditioning(conditioning)
        layout["copy_region"]["width"] = 0.2
        normalized["copy_prompt"] = "changed"

        self.assertEqual(self.layout["copy_region"]["width"], 0.45)
        self.assertEqual(conditioning["copy_prompt"], "  empty copy space  ")
        self.assertEqual(
            validate_regional_conditioning(conditioning)["copy_prompt"],
            "empty copy space",
        )

    def test_touching_regions_pass_but_interior_overlap_fails(self) -> None:
        touching = copy.deepcopy(self.layout)
        touching["subject_region"]["x"] = 0.45
        validate_regional_layout(touching)

        overlapping = copy.deepcopy(touching)
        overlapping["subject_region"]["x"] = 0.449
        with self.assertRaisesRegex(ValidationError, "invalid_regional_layout"):
            validate_regional_layout(overlapping)

    def test_separated_vertical_regions_are_valid(self) -> None:
        layout = copy.deepcopy(self.layout)
        layout["copy_region"] = {
            "x": 0.0,
            "y": 0.0,
            "width": 1.0,
            "height": 0.4,
        }
        layout["subject_region"] = {
            "x": 0.0,
            "y": 0.6,
            "width": 1.0,
            "height": 0.4,
        }

        self.assertEqual(validate_regional_layout(layout), layout)

    def test_layout_rejects_shape_number_bound_and_overlap_errors(self) -> None:
        invalid = []
        invalid.append(None)
        invalid.append({**self.layout, "extra": True})
        invalid.append({**self.layout, "mode": "arbitrary-regions"})
        for value in (True, math.nan, math.inf, -math.inf):
            changed = copy.deepcopy(self.layout)
            changed["copy_region"]["x"] = value
            invalid.append(changed)
        for field, value in (
            ("x", -0.01),
            ("x", 1.0),
            ("y", 1.0),
            ("width", 0.0),
            ("height", 0.0),
            ("width", 1.01),
        ):
            changed = copy.deepcopy(self.layout)
            changed["copy_region"][field] = value
            invalid.append(changed)
        overflow = copy.deepcopy(self.layout)
        overflow["subject_region"] = {
            "x": 0.9,
            "y": 0.0,
            "width": 0.2,
            "height": 1.0,
        }
        invalid.append(overflow)
        missing = copy.deepcopy(self.layout)
        del missing["copy_region"]["height"]
        invalid.append(missing)

        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError,
                "invalid_regional_layout",
            ):
                validate_regional_layout(value)

    def test_conditioning_rejects_shape_prompt_and_strength_errors(self) -> None:
        invalid = [
            None,
            {**self.conditioning, "extra": True},
            {key: value for key, value in self.conditioning.items() if key != "copy_prompt"},
            {**self.conditioning, "copy_prompt": " "},
            {**self.conditioning, "copy_prompt": 7},
            {**self.conditioning, "subject_prompt": "x" * 501},
            {**self.conditioning, "copy_strength": True},
            {**self.conditioning, "copy_strength": math.nan},
            {**self.conditioning, "copy_strength": -0.01},
            {**self.conditioning, "subject_strength": 2.01},
        ]

        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError,
                "invalid_regional_conditioning",
            ):
                validate_regional_conditioning(value)

    def test_strength_boundaries_are_inclusive(self) -> None:
        conditioning = {
            **self.conditioning,
            "copy_strength": 0.0,
            "subject_strength": 2.0,
        }

        self.assertEqual(validate_regional_conditioning(conditioning), conditioning)


class RegionalNodeInfoTests(unittest.TestCase):
    @staticmethod
    def area_info() -> dict[str, object]:
        return {
            "ConditioningSetAreaPercentage": {
                "input": {
                    "required": {
                        "conditioning": ["CONDITIONING", {}],
                        "width": ["FLOAT", {"min": 0.0}],
                        "height": ["FLOAT", {"min": 0.0}],
                        "x": ["FLOAT", {"min": 0.0}],
                        "y": ["FLOAT", {"min": 0.0}],
                        "strength": ["FLOAT", {"min": 0.0}],
                    },
                    "optional": {"future_hint": ["STRING", {}]},
                },
                "display_name": "Set Area Percentage",
            }
        }

    @staticmethod
    def combine_info() -> dict[str, object]:
        return {
            "ConditioningCombine": {
                "input": {
                    "required": {
                        "conditioning_1": ["CONDITIONING", {}],
                        "conditioning_2": ["CONDITIONING", {}],
                    }
                }
            }
        }

    def test_exact_required_signatures_accept_optional_metadata(self) -> None:
        self.assertIsNone(
            validate_regional_node_info(self.area_info(), self.combine_info())
        )

    def test_missing_extra_renamed_or_retyped_required_input_fails(self) -> None:
        invalid = []
        missing = self.area_info()
        del missing["ConditioningSetAreaPercentage"]["input"]["required"]["strength"]
        invalid.append((missing, self.combine_info()))
        extra = self.area_info()
        extra["ConditioningSetAreaPercentage"]["input"]["required"]["mask"] = [
            "MASK",
            {},
        ]
        invalid.append((extra, self.combine_info()))
        renamed = self.combine_info()
        renamed["ConditioningCombine"]["input"]["required"]["conditioning_x"] = (
            renamed["ConditioningCombine"]["input"]["required"].pop(
                "conditioning_2"
            )
        )
        invalid.append((self.area_info(), renamed))
        retyped = self.area_info()
        retyped["ConditioningSetAreaPercentage"]["input"]["required"]["width"][0] = (
            "INT"
        )
        invalid.append((retyped, self.combine_info()))
        malformed = self.combine_info()
        malformed["ConditioningCombine"]["input"]["required"]["conditioning_1"] = []
        invalid.append((self.area_info(), malformed))

        for area, combine in invalid:
            with self.subTest(area=area, combine=combine), self.assertRaisesRegex(
                ValidationError,
                "regional_layout_unavailable",
            ):
                validate_regional_node_info(area, combine)


if __name__ == "__main__":
    unittest.main()
