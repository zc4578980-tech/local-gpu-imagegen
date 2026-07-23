from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ValidationError  # noqa: E402
from local_gpu_imagegen.two_stage_layout import (  # noqa: E402
    build_control_identity,
    derive_subject_seed,
    validate_two_stage_conditioning,
    validate_two_stage_layout,
    validate_two_stage_node_info,
)


def exact_node_info() -> dict[str, object]:
    signatures = {
        "VAEEncodeForInpaint": {
            "pixels": "IMAGE",
            "vae": "VAE",
            "mask": "MASK",
            "grow_mask_by": "INT",
        },
        "SolidMask": {
            "value": "FLOAT",
            "width": "INT",
            "height": "INT",
        },
        "MaskComposite": {
            "destination": "MASK",
            "source": "MASK",
            "x": "INT",
            "y": "INT",
            "operation": "COMBO",
        },
        "FeatherMask": {
            "mask": "MASK",
            "left": "INT",
            "top": "INT",
            "right": "INT",
            "bottom": "INT",
        },
        "ImageCompositeMasked": {
            "destination": "IMAGE",
            "source": "IMAGE",
            "x": "INT",
            "y": "INT",
            "resize_source": "BOOLEAN",
        },
        "MaskToImage": {"mask": "MASK"},
    }
    result: dict[str, object] = {}
    for class_name, required in signatures.items():
        result[class_name] = {
            "input": {
                "required": {
                    name: [input_type, {}]
                    for name, input_type in required.items()
                },
                "optional": {"future_hint": ["STRING", {}]},
            },
            "display_name": class_name,
        }
    operation = result["MaskComposite"]["input"]["required"]["operation"]
    operation[1] = {"options": ["add", "subtract", "multiply"]}
    return result


class TwoStageLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = {
            "mode": "copy-subject-two-stage-v1",
            "canvas": {"width": 1280, "height": 720},
            "copy_protected_rect": {"x": 0, "y": 0, "width": 576, "height": 720},
            "subject_mask_rect": {"x": 720, "y": 24, "width": 512, "height": 672},
            "feather_pixels": 32,
            "vae_grow_mask_by": 8,
        }
        self.conditioning = {
            "subject_prompt": "one complete brass telescope on a tripod",
            "subject_negative_prompt": "cropped telescope, duplicate telescope, text",
            "subject_denoise": 0.9,
        }

    def test_approved_contract_is_normalized_and_deep_copied(self) -> None:
        layout = validate_two_stage_layout(self.layout)
        conditioning = validate_two_stage_conditioning(self.conditioning)
        layout["subject_mask_rect"]["x"] = 800
        self.assertEqual(self.layout["subject_mask_rect"]["x"], 720)
        self.assertEqual(conditioning["subject_denoise"], 0.9)

    def test_geometry_rejects_float_bool_alignment_overlap_and_margin_failures(self) -> None:
        changes = (
            ("canvas", "width", 1280.0),
            ("subject_mask_rect", "x", True),
            ("subject_mask_rect", "x", 721),
            ("subject_mask_rect", "x", 576),
            ("subject_mask_rect", "width", 640),
            ("copy_protected_rect", "width", 1280),
        )
        for section, field, value in changes:
            changed = copy.deepcopy(self.layout)
            changed[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaisesRegex(
                ValidationError, "invalid_two_stage_layout"
            ):
                validate_two_stage_layout(changed)

    def test_conditioning_trims_prompts_and_rejects_unknown_fields_or_denoise_bounds(self) -> None:
        trimmed = {**self.conditioning, "subject_prompt": "  telescope  "}
        self.assertEqual(validate_two_stage_conditioning(trimmed)["subject_prompt"], "telescope")
        for value in (
            {**self.conditioning, "extra": True},
            {**self.conditioning, "subject_prompt": " "},
            {**self.conditioning, "subject_negative_prompt": "x" * 2001},
            {**self.conditioning, "subject_denoise": 0.79},
            {**self.conditioning, "subject_denoise": 1.01},
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError, "invalid_two_stage_conditioning"
            ):
                validate_two_stage_conditioning(value)

    def test_subject_seed_wraps_exactly_and_control_digest_is_stable(self) -> None:
        self.assertEqual(derive_subject_seed(2026072303), 2026072304)
        self.assertEqual(derive_subject_seed(2**64 - 1), 0)
        first = build_control_identity(self.layout, "a" * 64, "base-subject-v1")
        second = build_control_identity(copy.deepcopy(self.layout), "a" * 64, "base-subject-v1")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_control_digest_has_golden_identity_and_rejects_or_changes_every_input(self) -> None:
        golden = build_control_identity(self.layout, "a" * 64, "base-subject-v1")
        self.assertEqual(
            golden,
            "6e3830417a1f917cb9455df891024cdb8e0505b8f0d7db38622b9fdc855e1080",
        )
        variants = []
        for section, field, value in (
            (None, "feather_pixels", 24),
            (None, "vae_grow_mask_by", 16),
            ("copy_protected_rect", "width", 568),
            ("subject_mask_rect", "x", 712),
            ("subject_mask_rect", "y", 32),
        ):
            changed = copy.deepcopy(self.layout)
            if section is None:
                changed[field] = value
            else:
                changed[section][field] = value
            variants.append(changed)
        for changed in variants:
            with self.subTest(layout=changed):
                self.assertNotEqual(
                    build_control_identity(changed, "a" * 64, "base-subject-v1"),
                    golden,
                )
        self.assertNotEqual(
            build_control_identity(self.layout, "b" * 64, "base-subject-v1"),
            golden,
        )
        with self.assertRaisesRegex(ValidationError, "invalid_two_stage_control"):
            build_control_identity(self.layout, "a" * 64, "base-subject-v2")

    def test_live_node_signatures_require_exact_required_types_and_mask_add(self) -> None:
        validate_two_stage_node_info(exact_node_info())
        changed = exact_node_info()
        changed["MaskComposite"]["input"]["required"]["operation"][1]["options"] = ["subtract"]
        with self.assertRaisesRegex(ValidationError, "two_stage_layout_unavailable"):
            validate_two_stage_node_info(changed)

    def test_every_live_node_rejects_required_input_signature_mutations(self) -> None:
        exact = exact_node_info()
        for class_name, node in exact.items():
            required = node["input"]["required"]
            original_name = next(iter(required))
            for mutation in ("missing", "renamed", "retyped", "newly_required"):
                changed = copy.deepcopy(exact)
                changed_required = changed[class_name]["input"]["required"]
                if mutation == "missing":
                    del changed_required[original_name]
                elif mutation == "renamed":
                    specification = changed_required.pop(original_name)
                    changed_required[f"{original_name}_renamed"] = specification
                elif mutation == "retyped":
                    changed_required[original_name][0] = "STRING"
                else:
                    changed_required["newly_required_input"] = ["INT", {}]
                with self.subTest(class_name=class_name, mutation=mutation), self.assertRaisesRegex(
                    ValidationError,
                    "two_stage_layout_unavailable",
                ):
                    validate_two_stage_node_info(changed)


if __name__ == "__main__":
    unittest.main()
