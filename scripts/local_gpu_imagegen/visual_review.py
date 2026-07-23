from __future__ import annotations

import copy
import re

from .errors import ValidationError
from .two_stage_layout import TWO_STAGE_TEMPLATE_ID


CHECK_NAMES = (
    "limb_separation",
    "feet_and_contact",
    "hands_and_held_objects",
    "text_and_watermarks",
)
ANATOMY_CHECKS = CHECK_NAMES[:3]
STATUSES = frozenset({"pass", "fail", "uncertain", "not_applicable"})
STAGE_CHECK_NAMES = (
    "base_copy_space",
    "base_subject_absent",
    "final_subject_inside_mask",
    "final_safe_margins",
    "final_forbidden_content",
    "feather_transition",
    "pixel_preservation",
)
STAGE_STATUSES = frozenset({"pass", "fail", "uncertain"})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def validate_visual_checks(value: object) -> dict[str, object]:
    expected = {"full_resolution_inspected", "prominent_human", *CHECK_NAMES}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError(
            "invalid_visual_checks",
            "Visual checks do not match the required structure.",
        )
    if value.get("full_resolution_inspected") is not True:
        raise ValidationError(
            "invalid_visual_checks",
            "Visual review requires an explicit full-resolution inspection.",
        )
    prominent_human = value.get("prominent_human")
    if not isinstance(prominent_human, bool):
        raise ValidationError(
            "invalid_visual_checks",
            "Visual review must state whether a prominent human is present.",
        )

    result = copy.deepcopy(value)
    for name in CHECK_NAMES:
        check = value.get(name)
        if not isinstance(check, dict) or set(check) != {"status", "observation"}:
            raise ValidationError(
                "invalid_visual_checks",
                f"Visual check {name} must contain only status and observation.",
            )
        status = check.get("status")
        observation = check.get("observation")
        if status not in STATUSES:
            raise ValidationError(
                "invalid_visual_checks",
                f"Visual check {name} has an unsupported status.",
            )
        if (
            not isinstance(observation, str)
            or not observation.strip()
            or len(observation.strip()) > 500
        ):
            raise ValidationError(
                "invalid_visual_checks",
                f"Visual check {name} requires a concise non-empty observation.",
            )
        if name in ANATOMY_CHECKS and (
            prominent_human and status == "not_applicable"
            or not prominent_human and status != "not_applicable"
        ):
            raise ValidationError(
                "inconsistent_visual_checks",
                "Anatomy applicability conflicts with prominent_human.",
            )
        if name == "text_and_watermarks" and status == "not_applicable":
            raise ValidationError(
                "inconsistent_visual_checks",
                "Text and watermark inspection is always applicable.",
            )
    return result


def visual_checks_pass(value: object) -> bool:
    try:
        checks = validate_visual_checks(value)
    except ValidationError:
        return False
    required = CHECK_NAMES if checks["prominent_human"] else ("text_and_watermarks",)
    return all(
        isinstance(checks.get(name), dict) and checks[name].get("status") == "pass"
        for name in required
    )


def validate_stage_checks(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(STAGE_CHECK_NAMES):
        raise ValidationError(
            "invalid_stage_checks",
            "Stage checks do not match the required two-stage structure.",
        )
    result = copy.deepcopy(value)
    for name in STAGE_CHECK_NAMES:
        check = value.get(name)
        if not isinstance(check, dict) or set(check) != {"status", "observation"}:
            raise ValidationError(
                "invalid_stage_checks",
                f"Stage check {name} must contain only status and observation.",
            )
        observation = check.get("observation")
        if (
            check.get("status") not in STAGE_STATUSES
            or not isinstance(observation, str)
            or not observation.strip()
            or len(observation.strip()) > 500
        ):
            raise ValidationError(
                "invalid_stage_checks",
                f"Stage check {name} has an invalid status or observation.",
            )
    return result


def stage_checks_pass(value: object) -> bool:
    try:
        checks = validate_stage_checks(value)
    except ValidationError:
        return False
    return all(checks[name]["status"] == "pass" for name in STAGE_CHECK_NAMES)


def is_two_stage_manifest(manifest: dict[str, object]) -> bool:
    request = manifest.get("request")
    return (
        isinstance(request, dict)
        and request.get("workflow_template_id") == TWO_STAGE_TEMPLATE_ID
    )


def pixel_preservation_passes(
    manifest: dict[str, object],
    round_number: object,
) -> bool:
    rounds = manifest.get("rounds")
    if not isinstance(rounds, list):
        return False
    selected = next(
        (
            value
            for value in rounds
            if isinstance(value, dict) and value.get("round_number") == round_number
        ),
        None,
    )
    report = selected.get("pixel_preservation") if isinstance(selected, dict) else None
    return (
        isinstance(report, dict)
        and type(report.get("checked_pixels")) is int
        and report["checked_pixels"] > 0
        and type(report.get("mismatched_pixels")) is int
        and report["mismatched_pixels"] == 0
        and type(report.get("copy_mismatched_pixels")) is int
        and report["copy_mismatched_pixels"] == 0
    )


def two_stage_review_passes(
    manifest: dict[str, object],
    review: dict[str, object],
    round_number: object | None = None,
) -> bool:
    if not is_two_stage_manifest(manifest):
        return "stage_checks" not in review
    selected_round = review.get("round_number") if round_number is None else round_number
    return (
        stage_checks_pass(review.get("stage_checks"))
        and pixel_preservation_passes(manifest, selected_round)
    )


def review_is_eligible(manifest: dict[str, object], review: dict[str, object]) -> bool:
    if review.get("next_action") != "finalize":
        return False
    if not visual_checks_pass(review.get("visual_checks")):
        return False
    if not two_stage_review_passes(manifest, review):
        return False

    failures = review.get("hard_failures")
    scores = review.get("scores")
    request = manifest.get("request")
    merged = request.get("merged_profile") if isinstance(request, dict) else None
    rubric = merged.get("rubric") if isinstance(merged, dict) else None
    if (
        not isinstance(failures, list)
        or failures
        or not isinstance(scores, dict)
        or not isinstance(rubric, dict)
    ):
        return False

    critical_dimensions = (
        name
        for name, specification in rubric.items()
        if isinstance(name, str)
        and isinstance(specification, dict)
        and specification.get("critical") is True
    )
    if not all(
        isinstance(scores.get(name), int)
        and not isinstance(scores.get(name), bool)
        and scores[name] >= 3
        for name in critical_dimensions
    ):
        return False

    preservation_results = review.get("preservation_results", [])
    if not isinstance(preservation_results, list):
        return False
    return not any(
        not isinstance(result, dict) or result.get("status") == "uncertain"
        for result in preservation_results
    )


def finalization_candidate(
    manifest: dict[str, object],
    round_number: int,
) -> dict[str, object] | None:
    if not isinstance(round_number, int) or isinstance(round_number, bool):
        return None
    run_id = manifest.get("run_id")
    rounds = manifest.get("rounds")
    reviews = manifest.get("reviews")
    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(rounds, list)
        or not isinstance(reviews, list)
    ):
        return None
    selected = next(
        (
            value
            for value in rounds
            if isinstance(value, dict) and value.get("round_number") == round_number
        ),
        None,
    )
    review = next(
        (
            value
            for value in reviews
            if isinstance(value, dict) and value.get("round_number") == round_number
        ),
        None,
    )
    if selected is None or review is None or not review_is_eligible(manifest, review):
        return None
    image = selected.get("image")
    image_sha256 = image.get("sha256") if isinstance(image, dict) else None
    if not isinstance(image_sha256, str) or SHA256_PATTERN.fullmatch(image_sha256) is None:
        return None
    return {
        "run_id": run_id,
        "round_number": round_number,
        "image_sha256": image_sha256,
        "confirmation": f"finalize:{run_id}:{round_number}:{image_sha256}",
        "quality_status": "candidate",
    }


def require_finalization_confirmation(
    manifest: dict[str, object],
    round_number: int,
    confirmation: object,
) -> dict[str, object]:
    candidate = finalization_candidate(manifest, round_number)
    if (
        candidate is None
        or not isinstance(confirmation, str)
        or confirmation != candidate["confirmation"]
    ):
        raise ValidationError(
            "finalization_confirmation_mismatch",
            "Finalization confirmation does not match an eligible retained image candidate.",
        )
    return candidate
