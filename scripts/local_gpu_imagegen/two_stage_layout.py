from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from .errors import ValidationError


TWO_STAGE_LAYOUT_MODE = "copy-subject-two-stage-v1"
TWO_STAGE_TEMPLATE_ID = "sdxl-two-stage-copy-subject"
SEED_DERIVATION_ID = "increment-mod-2^64-v1"
MAX_SEED = 2**64 - 1
RECT_FIELDS = frozenset({"x", "y", "width", "height"})
LAYOUT_FIELDS = frozenset({
    "mode", "canvas", "copy_protected_rect", "subject_mask_rect",
    "feather_pixels", "vae_grow_mask_by",
})
CONDITIONING_FIELDS = frozenset({
    "subject_prompt", "subject_negative_prompt", "subject_denoise",
})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TWO_STAGE_INPUT_TYPES = {
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


def derive_subject_seed(seed: object) -> int:
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValidationError("invalid_seed", "Seed must be an unsigned 64-bit integer.")
    return (seed + 1) & MAX_SEED


def validate_two_stage_layout(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != LAYOUT_FIELDS:
        raise _layout_error()
    if value["mode"] != TWO_STAGE_LAYOUT_MODE:
        raise _layout_error()
    canvas = _integer_record(value["canvas"], frozenset({"width", "height"}))
    copy_rect = _integer_record(value["copy_protected_rect"], RECT_FIELDS)
    subject_rect = _integer_record(value["subject_mask_rect"], RECT_FIELDS)
    width, height = canvas["width"], canvas["height"]
    feather, grow = value["feather_pixels"], value["vae_grow_mask_by"]
    if (
        width < 256 or height < 256 or width > 1536 or height > 1536
        or width % 8 or height % 8
        or any(number % 8 for number in (*copy_rect.values(), *subject_rect.values()))
        or copy_rect != {"x": 0, "y": 0, "width": copy_rect["width"], "height": height}
        or copy_rect["width"] * 100 < width * 35
        or not _inside(subject_rect, width, height)
        or subject_rect["x"] - copy_rect["width"] < 64
        or subject_rect["width"] < 256 or subject_rect["height"] < 256
        or width - subject_rect["x"] - subject_rect["width"] < 16
        or subject_rect["y"] < 16
        or height - subject_rect["y"] - subject_rect["height"] < 16
        or type(feather) is not int or not 0 <= feather <= 64
        or feather * 4 > min(subject_rect["width"], subject_rect["height"])
        or type(grow) is not int or not 0 <= grow <= 64
    ):
        raise _layout_error()
    return {
        "mode": TWO_STAGE_LAYOUT_MODE,
        "canvas": canvas,
        "copy_protected_rect": copy_rect,
        "subject_mask_rect": subject_rect,
        "feather_pixels": feather,
        "vae_grow_mask_by": grow,
    }


def validate_two_stage_conditioning(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != CONDITIONING_FIELDS:
        raise _conditioning_error()
    normalized = copy.deepcopy(value)
    for field in ("subject_prompt", "subject_negative_prompt"):
        text = normalized[field]
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 2000:
            raise _conditioning_error()
        normalized[field] = text.strip()
    denoise = normalized["subject_denoise"]
    if isinstance(denoise, bool) or not isinstance(denoise, (int, float)) or not math.isfinite(denoise):
        raise _conditioning_error()
    if not 0.80 <= float(denoise) <= 1.00:
        raise _conditioning_error()
    normalized["subject_denoise"] = float(denoise)
    return normalized


def build_control_identity(layout: object, workflow_sha256: object, stage_contract: object) -> str:
    normalized = validate_two_stage_layout(layout)
    if not isinstance(workflow_sha256, str) or SHA256_PATTERN.fullmatch(workflow_sha256) is None:
        raise ValidationError("invalid_two_stage_control", "Workflow SHA-256 is invalid.")
    if stage_contract != "base-subject-v1":
        raise ValidationError("invalid_two_stage_control", "Stage contract is invalid.")
    document = {
        "schema_version": 1,
        "layout": normalized,
        "workflow_sha256": workflow_sha256,
        "seed_derivation_id": SEED_DERIVATION_ID,
        "stage_contract": stage_contract,
        "output_roles": ["base", "mask", "final"],
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def validate_two_stage_node_info(value: object) -> None:
    for class_name, expected_types in _TWO_STAGE_INPUT_TYPES.items():
        if _required_types(value, class_name) != expected_types:
            raise _node_info_error()

    node = value.get("MaskComposite") if isinstance(value, dict) else None
    inputs = node.get("input") if isinstance(node, dict) else None
    required = inputs.get("required") if isinstance(inputs, dict) else None
    operation = required.get("operation") if isinstance(required, dict) else None
    metadata = operation[1] if isinstance(operation, list) and len(operation) > 1 else None
    options = metadata.get("options") if isinstance(metadata, dict) else None
    if not isinstance(options, list) or "add" not in options:
        raise _node_info_error()


def _integer_record(value: object, fields: frozenset[str]) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _layout_error()
    if any(type(value[field]) is not int for field in fields):
        raise _layout_error()
    return {field: value[field] for field in value}


def _inside(rect: dict[str, int], width: int, height: int) -> bool:
    return (
        rect["x"] >= 0
        and rect["y"] >= 0
        and rect["width"] > 0
        and rect["height"] > 0
        and rect["x"] + rect["width"] <= width
        and rect["y"] + rect["height"] <= height
    )


def _required_types(value: object, class_name: str) -> dict[str, str]:
    node = value.get(class_name) if isinstance(value, dict) else None
    inputs = node.get("input") if isinstance(node, dict) else None
    required = inputs.get("required") if isinstance(inputs, dict) else None
    if not isinstance(required, dict):
        raise _node_info_error()
    result: dict[str, str] = {}
    for name, specification in required.items():
        if (
            not isinstance(name, str)
            or not isinstance(specification, list)
            or not specification
            or not isinstance(specification[0], str)
        ):
            raise _node_info_error()
        result[name] = specification[0]
    return result


def _layout_error() -> ValidationError:
    return ValidationError(
        "invalid_two_stage_layout",
        "Two-stage layout is outside the copy-subject-two-stage-v1 contract.",
    )


def _conditioning_error() -> ValidationError:
    return ValidationError(
        "invalid_two_stage_conditioning",
        "Two-stage conditioning is outside the approved contract.",
    )


def _node_info_error() -> ValidationError:
    return ValidationError(
        "two_stage_layout_unavailable",
        "Required ComfyUI two-stage node signatures are unavailable.",
    )
