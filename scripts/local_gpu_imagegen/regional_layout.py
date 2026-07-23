from __future__ import annotations

import copy
import math

from .errors import ValidationError


LAYOUT_MODE = "copy-subject-v1"
REGIONAL_TEMPLATE_ID = "sdxl-regional-txt2img"
REGION_FIELDS = frozenset({"x", "y", "width", "height"})
CONDITIONING_FIELDS = frozenset({
    "copy_prompt",
    "copy_strength",
    "subject_prompt",
    "subject_strength",
})
_LAYOUT_FIELDS = frozenset({"mode", "copy_region", "subject_region"})
_AREA_INPUT_TYPES = {
    "conditioning": "CONDITIONING",
    "width": "FLOAT",
    "height": "FLOAT",
    "x": "FLOAT",
    "y": "FLOAT",
    "strength": "FLOAT",
}
_COMBINE_INPUT_TYPES = {
    "conditioning_1": "CONDITIONING",
    "conditioning_2": "CONDITIONING",
}


def validate_regional_layout(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _LAYOUT_FIELDS:
        raise _layout_error()
    if value["mode"] != LAYOUT_MODE:
        raise _layout_error()

    normalized: dict[str, object] = {"mode": LAYOUT_MODE}
    for name in ("copy_region", "subject_region"):
        region = value[name]
        if not isinstance(region, dict) or set(region) != REGION_FIELDS:
            raise _layout_error()
        if any(not _number(region[field]) for field in REGION_FIELDS):
            raise _layout_error()
        x = float(region["x"])
        y = float(region["y"])
        width = float(region["width"])
        height = float(region["height"])
        if not (
            0.0 <= x < 1.0
            and 0.0 <= y < 1.0
            and 0.0 < width <= 1.0
            and 0.0 < height <= 1.0
            and x + width <= 1.0
            and y + height <= 1.0
        ):
            raise _layout_error()
        normalized[name] = copy.deepcopy(region)

    copy_region = normalized["copy_region"]
    subject_region = normalized["subject_region"]
    assert isinstance(copy_region, dict) and isinstance(subject_region, dict)
    horizontal_overlap = min(
        copy_region["x"] + copy_region["width"],
        subject_region["x"] + subject_region["width"],
    ) - max(copy_region["x"], subject_region["x"])
    vertical_overlap = min(
        copy_region["y"] + copy_region["height"],
        subject_region["y"] + subject_region["height"],
    ) - max(copy_region["y"], subject_region["y"])
    if horizontal_overlap > 0.0 and vertical_overlap > 0.0:
        raise _layout_error()
    return normalized


def validate_regional_conditioning(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != CONDITIONING_FIELDS:
        raise _conditioning_error()
    normalized = copy.deepcopy(value)
    for field in ("copy_prompt", "subject_prompt"):
        prompt = normalized[field]
        if not isinstance(prompt, str):
            raise _conditioning_error()
        prompt = prompt.strip()
        if not prompt or len(prompt) > 500:
            raise _conditioning_error()
        normalized[field] = prompt
    for field in ("copy_strength", "subject_strength"):
        strength = normalized[field]
        if not _number(strength) or not 0.0 <= float(strength) <= 2.0:
            raise _conditioning_error()
    return normalized


def validate_regional_node_info(
    area_info: object,
    combine_info: object,
) -> None:
    area = _required_types(area_info, "ConditioningSetAreaPercentage")
    combine = _required_types(combine_info, "ConditioningCombine")
    if area != _AREA_INPUT_TYPES or combine != _COMBINE_INPUT_TYPES:
        raise ValidationError(
            "regional_layout_unavailable",
            "Required ComfyUI regional node signatures are unavailable.",
        )


def _required_types(value: object, class_name: str) -> dict[str, str]:
    node = value.get(class_name) if isinstance(value, dict) else None
    inputs = node.get("input") if isinstance(node, dict) else None
    required = inputs.get("required") if isinstance(inputs, dict) else None
    if not isinstance(required, dict):
        raise ValidationError(
            "regional_layout_unavailable",
            "Required ComfyUI regional node is unavailable.",
        )
    result: dict[str, str] = {}
    for name, specification in required.items():
        if (
            not isinstance(name, str)
            or not isinstance(specification, list)
            or not specification
            or not isinstance(specification[0], str)
        ):
            raise ValidationError(
                "regional_layout_unavailable",
                "ComfyUI regional node signature is malformed.",
            )
        result[name] = specification[0]
    return result


def _number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _layout_error() -> ValidationError:
    return ValidationError(
        "invalid_regional_layout",
        "Regional layout is outside the copy-subject-v1 contract.",
    )


def _conditioning_error() -> ValidationError:
    return ValidationError(
        "invalid_regional_conditioning",
        "Regional conditioning is outside the copy-subject-v1 contract.",
    )
