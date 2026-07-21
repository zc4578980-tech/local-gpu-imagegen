from __future__ import annotations

import copy
from collections.abc import Collection

from .errors import ArtifactError


SUPPORTED_BACKENDS = frozenset({"webui", "diffusers", "comfyui"})
BACKEND_RESULT_REQUIRED = {
    "ok", "path", "backend", "mode", "seed", "width", "height", "model",
    "endpoint_identity", "model_identity_token", "identity_strength",
    "workflow_template_id", "workflow_template_version", "prompt_compiler_id",
    "prompt_compiler_version",
}


def validate_backend_result(
    value: object,
    expected_mode: str,
    expected_width: int,
    expected_height: int,
    *,
    expected_seed: int | None = None,
    expected_backend: str | None = None,
    available_backends: Collection[str] = tuple(sorted(SUPPORTED_BACKENDS)),
) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise ArtifactError("invalid_backend_result", "Backend result must be a successful object.")
    missing = sorted(BACKEND_RESULT_REQUIRED - set(value))
    if missing:
        raise ArtifactError(
            "invalid_backend_result",
            "Backend result is missing required fields.",
            {"fields": missing},
        )
    backend = value["backend"]
    mode = value["mode"]
    if (
        not isinstance(backend, str)
        or backend not in SUPPORTED_BACKENDS
        or not isinstance(mode, str)
        or not isinstance(expected_mode, str)
        or mode != expected_mode
    ):
        raise ArtifactError("invalid_backend_result", "Backend or mode does not match the request.")
    if expected_backend is not None and not isinstance(expected_backend, str):
        raise ArtifactError("invalid_backend_result", "Expected backend is invalid.")
    if (
        not isinstance(available_backends, (list, tuple, set, frozenset))
        or not all(isinstance(candidate, str) for candidate in available_backends)
    ):
        raise ArtifactError("invalid_backend_result", "Advertised backends are invalid.")
    if expected_backend in SUPPORTED_BACKENDS and backend != expected_backend:
        raise ArtifactError("invalid_backend_result", "Backend does not match the requested backend.")
    if expected_backend not in {None, *SUPPORTED_BACKENDS}:
        raise ArtifactError("invalid_backend_result", "Expected backend is invalid.")
    if backend not in available_backends:
        raise ArtifactError("invalid_backend_result", "Backend is not currently advertised as available.")
    if (
        type(expected_width) is not int
        or type(expected_height) is not int
        or type(value["width"]) is not int
        or type(value["height"]) is not int
        or value["width"] != expected_width
        or value["height"] != expected_height
    ):
        raise ArtifactError("invalid_backend_result", "Backend dimensions do not match the request.")
    if not isinstance(value["path"], str) or not value["path"]:
        raise ArtifactError("invalid_backend_result", "Backend path must be non-empty.")
    if type(value["seed"]) not in {int, type(None)}:
        raise ArtifactError("invalid_backend_result", "Backend seed must be an integer or null.")
    if type(expected_seed) not in {int, type(None)}:
        raise ArtifactError("invalid_backend_result", "Expected seed is invalid.")
    if expected_seed is not None and value["seed"] != expected_seed:
        raise ArtifactError("invalid_backend_result", "Backend seed does not match the request.")
    for field in (
        "model", "endpoint_identity", "model_identity_token", "identity_strength",
        "prompt_compiler_id",
    ):
        if not isinstance(value[field], str) or not value[field]:
            raise ArtifactError("invalid_backend_result", f"Backend {field} must be non-empty.")
    if value["identity_strength"] not in {"cryptographic", "backend_binding", "local"}:
        raise ArtifactError("invalid_backend_result", "Backend identity strength is invalid.")
    if type(value["prompt_compiler_version"]) is not int or value["prompt_compiler_version"] < 1:
        raise ArtifactError("invalid_backend_result", "Backend prompt compiler version is invalid.")
    workflow_id = value["workflow_template_id"]
    workflow_version = value["workflow_template_version"]
    if backend == "comfyui":
        if (
            not isinstance(workflow_id, str)
            or not workflow_id
            or type(workflow_version) is not int
            or workflow_version < 1
            or not isinstance(value.get("workflow_job_id"), str)
            or not value["workflow_job_id"]
        ):
            raise ArtifactError("invalid_backend_result", "ComfyUI workflow result is incomplete.")
    elif workflow_id is not None or workflow_version is not None or "workflow_job_id" in value:
        raise ArtifactError("invalid_backend_result", "Non-ComfyUI results cannot claim a workflow job.")
    return copy.deepcopy(value)
