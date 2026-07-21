from __future__ import annotations

import copy
import json

from .errors import ValidationError


PLAN_REQUIRED = {
    "profile", "style", "intent", "positive_prompt", "negative_prompt",
    "constraints", "model_choice", "backend", "parameters", "max_rounds",
    "upscale_policy",
}
_BACKENDS = {"auto", "webui", "diffusers"}
_UPSCALE_POLICIES = {"auto", "off"}


def validate_generation_plan(
    plan: dict[str, object],
    run_request: dict[str, object],
    action: str,
    edit_mode: str = "txt2img",
) -> dict[str, object]:
    if not isinstance(plan, dict):
        raise ValidationError("invalid_generation_plan", "Generation plan must be an object.")
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
        raise ValidationError("invalid_backend", "backend must be auto, webui, or diffusers.")
    if plan["model_choice"] is not None and (
        not isinstance(plan["model_choice"], str) or not plan["model_choice"].strip()
    ):
        raise ValidationError("invalid_model_choice", "model_choice must be a non-empty string or null.")
    if not isinstance(plan["upscale_policy"], str) or plan["upscale_policy"] not in _UPSCALE_POLICIES:
        raise ValidationError("invalid_upscale_policy", "upscale_policy must be auto or off.")
    if type(plan["max_rounds"]) is not int or not 1 <= plan["max_rounds"] <= 3:
        raise ValidationError("invalid_round_budget", "max_rounds must be an integer from 1 to 3.")
    if action not in {"initial", "refine", "explore"}:
        raise ValidationError("invalid_generation_action", "action must be initial, refine, or explore.")

    _validate_confirmed_boundary(plan, run_request)
    _validate_backend(plan["backend"], run_request)
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
    return copy.deepcopy(plan)


def _validate_confirmed_boundary(plan: dict[str, object], run_request: dict[str, object]) -> None:
    validate_confirmed_run_request(run_request)
    for field in ("profile", "style", "intent", "model_choice", "max_rounds", "upscale_policy"):
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
        "upscale_policy", "backend", "available_backends",
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
    if run_request["model_choice"] is not None and (
        not isinstance(run_request["model_choice"], str) or not run_request["model_choice"].strip()
    ):
        raise ValidationError("invalid_run_request", "Confirmed model_choice must be a non-empty string or null.")
    if type(run_request["max_rounds"]) is not int or not 1 <= run_request["max_rounds"] <= 3:
        raise ValidationError("invalid_run_request", "Confirmed max_rounds must be an integer from 1 to 3.")
    if not isinstance(run_request["upscale_policy"], str) or run_request["upscale_policy"] not in _UPSCALE_POLICIES:
        raise ValidationError("invalid_run_request", "Confirmed upscale_policy is invalid.")
    if not isinstance(run_request["backend"], str) or run_request["backend"] not in _BACKENDS:
        raise ValidationError("invalid_backend", "Confirmed backend must be auto, webui, or diffusers.")
    available = run_request["available_backends"]
    if not isinstance(available, (list, tuple, set)) or not all(isinstance(candidate, str) for candidate in available):
        raise ValidationError("invalid_run_request", "available_backends must be a collection of backend names.")
    available_values = list(available)
    if len(set(available_values)) != len(available_values) or any(
        candidate not in {"webui", "diffusers"} for candidate in available_values
    ):
        raise ValidationError("invalid_backend", "available_backends contains an unsupported or duplicate backend.")
    backend = run_request["backend"]
    if backend == "auto" and not available_values:
        raise ValidationError("invalid_backend", "Auto backend requires at least one advertised supported backend.")
    if backend in {"webui", "diffusers"} and backend not in available_values:
        raise ValidationError("invalid_backend", "Confirmed backend must be advertised as available.")
    return copy.deepcopy(run_request)


def _validate_backend(backend: object, run_request: dict[str, object]) -> None:
    confirmed_backend = run_request["backend"]
    if confirmed_backend != "auto":
        if backend != confirmed_backend:
            raise ValidationError("generation_plan_mismatch", "Generation plan backend differs from confirmed run.", {"field": "backend"})
        return
    available = run_request["available_backends"]
    advertised = {
        candidate for candidate in available
        if isinstance(candidate, str) and candidate in {"webui", "diffusers"}
    }
    if backend not in advertised:
        raise ValidationError("invalid_backend", "Auto backend must resolve to an advertised WebUI or Diffusers backend.")


def _merged_profile(run_request: dict[str, object]) -> dict[str, object]:
    for field in ("merged_profile", "profile_document", "profile_definition"):
        value = run_request.get(field)
        if isinstance(value, dict):
            return value
    return {}
