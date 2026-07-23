from __future__ import annotations

import copy
import json

from .errors import ValidationError
from .regional_layout import (
    REGIONAL_TEMPLATE_ID,
    validate_regional_conditioning,
    validate_regional_layout,
)
from .two_stage_layout import (
    TWO_STAGE_TEMPLATE_ID,
    validate_two_stage_conditioning,
    validate_two_stage_layout,
)


CONFIRMED_ROUTE_FIELDS = frozenset({
    "authorization_scope", "route_token", "model_choice", "backend", "endpoint_identity",
    "model_identity_token", "identity_strength", "workflow_template_id",
    "workflow_template_version", "prompt_compiler_id", "prompt_compiler_version",
})
PLAN_REQUIRED = {
    "profile", "style", "intent", "positive_prompt", "negative_prompt",
    "constraints", "parameters", "max_rounds", "upscale_policy",
} | set(CONFIRMED_ROUTE_FIELDS)
_BACKENDS = {"webui", "diffusers", "comfyui"}
_UPSCALE_POLICIES = {"auto", "off"}


def validate_generation_plan(
    plan: dict[str, object],
    run_request: dict[str, object],
    action: str,
    edit_mode: str = "txt2img",
) -> dict[str, object]:
    if not isinstance(plan, dict):
        raise ValidationError("invalid_generation_plan", "Generation plan must be an object.")
    plan = copy.deepcopy(plan)
    fields = set(plan)
    if fields != PLAN_REQUIRED:
        raise ValidationError(
            "invalid_generation_plan",
            "Generation plan fields do not match the published schema.",
            {"missing": sorted(PLAN_REQUIRED - fields), "extra": sorted(fields - PLAN_REQUIRED)},
        )
    if not isinstance(plan["positive_prompt"], str) or not plan["positive_prompt"].strip():
        raise ValidationError("invalid_positive_prompt", "positive_prompt must be a non-empty string.")
    if not isinstance(plan["negative_prompt"], str):
        raise ValidationError("invalid_negative_prompt", "negative_prompt must be a string.")
    if not isinstance(plan["constraints"], dict) or not isinstance(plan["parameters"], dict):
        raise ValidationError("invalid_generation_plan", "constraints and parameters must be objects.")
    if edit_mode not in {"txt2img", "img2img", "inpaint"}:
        raise ValidationError("invalid_edit_mode", "edit_mode must be txt2img, img2img, or inpaint.")
    nested_mode = plan["parameters"].get("mode")
    if nested_mode is not None and nested_mode != edit_mode:
        raise ValidationError(
            "edit_mode_mismatch",
            "Generation plan parameters.mode must match the authoritative edit_mode.",
            {"edit_mode": edit_mode, "plan_mode": nested_mode},
        )
    if not isinstance(plan["backend"], str) or plan["backend"] not in _BACKENDS:
        raise ValidationError("invalid_backend", "backend must be webui, diffusers, or comfyui.")
    if not isinstance(plan["model_choice"], str) or not plan["model_choice"].strip():
        raise ValidationError("invalid_model_choice", "model_choice must be a non-empty string.")
    if not isinstance(plan["upscale_policy"], str) or plan["upscale_policy"] not in _UPSCALE_POLICIES:
        raise ValidationError("invalid_upscale_policy", "upscale_policy must be auto or off.")
    if type(plan["max_rounds"]) is not int or not 1 <= plan["max_rounds"] <= 3:
        raise ValidationError("invalid_round_budget", "max_rounds must be an integer from 1 to 3.")
    if action not in {"initial", "refine", "explore"}:
        raise ValidationError("invalid_generation_action", "action must be initial, refine, or explore.")

    _validate_confirmed_boundary(plan, run_request)
    _validate_backend(plan["backend"], run_request)
    _validate_regional_plan(plan, run_request, action)
    _validate_two_stage_plan(plan, run_request, action)
    if action != "initial":
        profile = _merged_profile(run_request)
        mutable = profile.get(f"{action}_mutable", [])
        if not isinstance(mutable, list) or not all(isinstance(name, str) for name in mutable):
            raise ValidationError("invalid_profile_document", f"{action}_mutable must be a list of strings.")
        disallowed = sorted(set(plan["parameters"]) - set(mutable))
        if disallowed:
            raise ValidationError(
                "parameter_not_allowed",
                f"Parameters are not mutable for {action}: {', '.join(disallowed)}",
                {"action": action, "parameters": disallowed},
            )
    return plan


def _validate_confirmed_boundary(plan: dict[str, object], run_request: dict[str, object]) -> None:
    validate_confirmed_run_request(run_request)
    for field in (
        "profile", "style", "intent", "model_choice", "max_rounds", "upscale_policy",
        *CONFIRMED_ROUTE_FIELDS,
    ):
        if field in run_request and plan[field] != run_request[field]:
            raise ValidationError("generation_plan_mismatch", f"Generation plan {field} differs from confirmed run.", {"field": field})
    explicit_constraints = run_request.get("constraints", {})
    if not isinstance(explicit_constraints, dict):
        raise ValidationError("invalid_run_request", "Confirmed constraints must be an object.")
    for name, value in explicit_constraints.items():
        if plan["constraints"].get(name) != value:
            raise ValidationError("generation_plan_mismatch", f"Generation plan constraint differs from confirmed run: {name}", {"field": name})


def validate_confirmed_run_request(run_request: object) -> dict[str, object]:
    if not isinstance(run_request, dict):
        raise ValidationError("invalid_run_request", "Confirmed run request must be an object.")
    required = {
        "profile", "style", "intent", "constraints", "model_choice", "max_rounds",
        "upscale_policy", "backend", "available_backends", "authorization_scope",
        "route_token", "route",
    }
    missing = sorted(required - set(run_request))
    if missing:
        raise ValidationError("invalid_run_request", f"Confirmed run request is missing: {', '.join(missing)}", {"fields": missing})
    if not isinstance(run_request["profile"], str) or not run_request["profile"].strip():
        raise ValidationError("invalid_run_request", "Confirmed profile must be a non-empty string.")
    if run_request["style"] is not None and (
        not isinstance(run_request["style"], str) or not run_request["style"].strip()
    ):
        raise ValidationError("invalid_run_request", "Confirmed style must be a non-empty string or null.")
    if not isinstance(run_request["intent"], str) or not run_request["intent"].strip():
        raise ValidationError("invalid_run_request", "Confirmed intent must be a non-empty string.")
    if not isinstance(run_request["constraints"], dict):
        raise ValidationError("invalid_run_request", "Confirmed constraints must be an object.")
    try:
        json.dumps(run_request["constraints"], allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValidationError("invalid_run_request", "Confirmed constraints must be JSON serializable.") from error
    if not isinstance(run_request["model_choice"], str) or not run_request["model_choice"].strip():
        raise ValidationError("invalid_run_request", "Confirmed model_choice must be a non-empty string.")
    if type(run_request["max_rounds"]) is not int or not 1 <= run_request["max_rounds"] <= 3:
        raise ValidationError("invalid_run_request", "Confirmed max_rounds must be an integer from 1 to 3.")
    if not isinstance(run_request["upscale_policy"], str) or run_request["upscale_policy"] not in _UPSCALE_POLICIES:
        raise ValidationError("invalid_run_request", "Confirmed upscale_policy is invalid.")
    if not isinstance(run_request["backend"], str) or run_request["backend"] not in _BACKENDS:
        raise ValidationError("invalid_backend", "Confirmed backend must be webui, diffusers, or comfyui.")
    if run_request["authorization_scope"] not in {"private", "public_evidence"}:
        raise ValidationError("invalid_authorization_scope", "Confirmed authorization scope is invalid.")
    if not isinstance(run_request["route_token"], str) or not run_request["route_token"].startswith("route:"):
        raise ValidationError("invalid_run_request", "Confirmed route token is invalid.")
    route = run_request["route"]
    if not isinstance(route, dict):
        raise ValidationError("invalid_run_request", "Confirmed route must be an object.")
    route_pairs = {
        "authorization_scope": "authorization_scope",
        "route_token": "route_token",
        "model_id": "model_choice",
        "backend": "backend",
        "endpoint_identity": "endpoint_identity",
        "identity_token": "model_identity_token",
        "identity_strength": "identity_strength",
        "workflow_template_id": "workflow_template_id",
        "workflow_template_version": "workflow_template_version",
        "prompt_compiler_id": "prompt_compiler_id",
        "prompt_compiler_version": "prompt_compiler_version",
    }
    missing_route = sorted(set(route_pairs) - set(route))
    if missing_route:
        raise ValidationError("invalid_run_request", "Confirmed route is incomplete.", {"fields": missing_route})
    for route_field, request_field in route_pairs.items():
        if route[route_field] != run_request.get(request_field):
            raise ValidationError(
                "invalid_run_request",
                "Confirmed route differs from the persisted run boundary.",
                {"field": route_field},
            )
    available = run_request["available_backends"]
    if not isinstance(available, (list, tuple, set)) or not all(isinstance(candidate, str) for candidate in available):
        raise ValidationError("invalid_run_request", "available_backends must be a collection of backend names.")
    available_values = list(available)
    if len(set(available_values)) != len(available_values) or any(
        candidate not in _BACKENDS for candidate in available_values
    ):
        raise ValidationError("invalid_backend", "available_backends contains an unsupported or duplicate backend.")
    backend = run_request["backend"]
    if backend not in available_values:
        raise ValidationError("invalid_backend", "Confirmed backend must be advertised as available.")
    normalized = copy.deepcopy(run_request)
    normalized_constraints = normalized["constraints"]
    assert isinstance(normalized_constraints, dict)
    regional_route = route.get("workflow_template_id") == REGIONAL_TEMPLATE_ID
    two_stage_route = route.get("workflow_template_id") == TWO_STAGE_TEMPLATE_ID
    has_layout = "regional_layout" in normalized_constraints
    has_conditioning = "initial_regional_conditioning" in normalized
    has_two_stage_layout = "two_stage_layout" in normalized_constraints
    has_two_stage_conditioning = "initial_two_stage_conditioning" in normalized
    if (
        two_stage_route != has_two_stage_layout
        or two_stage_route != has_two_stage_conditioning
    ):
        raise ValidationError(
            "invalid_two_stage_conditioning",
            "Two-stage route data is incomplete or not allowed on this route.",
        )
    if two_stage_route:
        if has_layout or has_conditioning:
            raise ValidationError(
                "invalid_regional_conditioning",
                "Two-stage routes cannot accept regional data.",
            )
        layout = validate_two_stage_layout(
            normalized_constraints.get("two_stage_layout")
        )
        conditioning = validate_two_stage_conditioning(
            normalized.get("initial_two_stage_conditioning")
        )
        requirements = route.get("requirements")
        route_layout = validate_two_stage_layout(
            requirements.get("two_stage_layout") if isinstance(requirements, dict) else None
        )
        if route_layout != layout:
            raise ValidationError(
                "invalid_run_request",
                "Confirmed two-stage layout differs from the route requirements.",
            )
        canvas = layout["canvas"]
        if (
            normalized_constraints.get("width") != canvas["width"]
            or normalized_constraints.get("height") != canvas["height"]
        ):
            raise ValidationError(
                "invalid_two_stage_layout",
                "Confirmed dimensions must match the two-stage canvas.",
            )
        normalized_constraints["two_stage_layout"] = layout
        normalized["initial_two_stage_conditioning"] = conditioning
        return normalized
    if regional_route:
        layout = validate_regional_layout(normalized_constraints.get("regional_layout"))
        conditioning = validate_regional_conditioning(
            normalized.get("initial_regional_conditioning")
        )
        requirements = route.get("requirements")
        route_layout = validate_regional_layout(
            requirements.get("regional_layout") if isinstance(requirements, dict) else None
        )
        if route_layout != layout:
            raise ValidationError(
                "invalid_run_request",
                "Confirmed regional layout differs from the route requirements.",
            )
        normalized_constraints["regional_layout"] = layout
        normalized["initial_regional_conditioning"] = conditioning
    elif has_layout or has_conditioning:
        raise ValidationError(
            "invalid_regional_conditioning",
            "Standard routes cannot accept regional data.",
        )
    return normalized


def _validate_regional_plan(
    plan: dict[str, object],
    run_request: dict[str, object],
    action: str,
) -> None:
    constraints = plan["constraints"]
    parameters = plan["parameters"]
    assert isinstance(constraints, dict) and isinstance(parameters, dict)
    regional_route = plan["workflow_template_id"] == REGIONAL_TEMPLATE_ID
    has_layout = "regional_layout" in constraints
    has_conditioning = "regional_conditioning" in parameters
    if regional_route:
        layout = validate_regional_layout(constraints.get("regional_layout"))
        conditioning = validate_regional_conditioning(
            parameters.get("regional_conditioning")
        )
        initial = validate_regional_conditioning(
            run_request.get("initial_regional_conditioning")
        )
        if action == "initial" and conditioning != initial:
            raise ValidationError(
                "generation_plan_mismatch",
                "Initial regional conditioning differs from confirmation.",
            )
        constraints["regional_layout"] = layout
        parameters["regional_conditioning"] = conditioning
    elif (
        has_layout
        or has_conditioning
        or "initial_regional_conditioning" in run_request
    ):
        raise ValidationError(
            "invalid_regional_conditioning",
            "Standard routes cannot accept regional data.",
        )


def _validate_two_stage_plan(
    plan: dict[str, object],
    run_request: dict[str, object],
    action: str,
) -> None:
    constraints = plan["constraints"]
    parameters = plan["parameters"]
    assert isinstance(constraints, dict) and isinstance(parameters, dict)
    two_stage_route = plan["workflow_template_id"] == TWO_STAGE_TEMPLATE_ID
    has_layout = "two_stage_layout" in constraints
    has_conditioning = "two_stage_conditioning" in parameters
    if two_stage_route != has_layout or two_stage_route != has_conditioning:
        raise ValidationError(
            "invalid_two_stage_conditioning",
            "Two-stage route data is incomplete.",
        )
    if two_stage_route:
        layout = validate_two_stage_layout(constraints.get("two_stage_layout"))
        conditioning = validate_two_stage_conditioning(
            parameters.get("two_stage_conditioning")
        )
        initial = validate_two_stage_conditioning(
            run_request.get("initial_two_stage_conditioning")
        )
        if action == "initial" and conditioning != initial:
            raise ValidationError(
                "generation_plan_mismatch",
                "Initial two-stage conditioning differs from confirmation.",
            )
        canvas = layout["canvas"]
        if constraints.get("width") != canvas["width"] or constraints.get("height") != canvas["height"]:
            raise ValidationError(
                "invalid_two_stage_layout",
                "Generation dimensions must match the two-stage canvas.",
            )
        constraints["two_stage_layout"] = layout
        parameters["two_stage_conditioning"] = conditioning
    elif "initial_two_stage_conditioning" in run_request:
        raise ValidationError(
            "invalid_two_stage_conditioning",
            "Standard routes cannot accept two-stage data.",
        )


def _validate_backend(backend: object, run_request: dict[str, object]) -> None:
    confirmed_backend = run_request["backend"]
    if backend != confirmed_backend:
        raise ValidationError("generation_plan_mismatch", "Generation plan backend differs from confirmed run.", {"field": "backend"})


def _merged_profile(run_request: dict[str, object]) -> dict[str, object]:
    for field in ("merged_profile", "profile_document", "profile_definition"):
        value = run_request.get(field)
        if isinstance(value, dict):
            return value
    return {}
