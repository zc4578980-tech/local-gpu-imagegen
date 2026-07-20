from __future__ import annotations

import copy
from collections.abc import Collection

from .errors import ArtifactError


BACKEND_RESULT_REQUIRED = {"ok", "path", "backend", "mode", "seed", "width", "height"}


def validate_backend_result(
    value: object,
    expected_mode: str,
    expected_width: int,
    expected_height: int,
    *,
    expected_seed: int | None = None,
    expected_backend: str | None = None,
    available_backends: Collection[str] = ("webui", "diffusers"),
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
    if backend not in {"webui", "diffusers"} or value["mode"] != expected_mode:
        raise ArtifactError("invalid_backend_result", "Backend or mode does not match the request.")
    if expected_backend in {"webui", "diffusers"} and backend != expected_backend:
        raise ArtifactError("invalid_backend_result", "Backend does not match the requested backend.")
    if expected_backend == "auto" and (backend not in available_backends or backend not in {"webui", "diffusers"}):
        raise ArtifactError("invalid_backend_result", "Auto backend did not resolve to an advertised supported backend.")
    if expected_backend not in {None, "auto", "webui", "diffusers"}:
        raise ArtifactError("invalid_backend_result", "Expected backend is invalid.")
    if (
        type(value["width"]) is not int
        or type(value["height"]) is not int
        or value["width"] != expected_width
        or value["height"] != expected_height
    ):
        raise ArtifactError("invalid_backend_result", "Backend dimensions do not match the request.")
    if not isinstance(value["path"], str) or not value["path"]:
        raise ArtifactError("invalid_backend_result", "Backend path must be non-empty.")
    if type(value["seed"]) not in {int, type(None)}:
        raise ArtifactError("invalid_backend_result", "Backend seed must be an integer or null.")
    if expected_seed is not None and value["seed"] != expected_seed:
        raise ArtifactError("invalid_backend_result", "Backend seed does not match the request.")
    return copy.deepcopy(value)
