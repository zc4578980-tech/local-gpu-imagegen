from __future__ import annotations

import copy

from .errors import ArtifactError


BACKEND_RESULT_REQUIRED = {"ok", "path", "backend", "mode", "seed", "width", "height"}


def validate_backend_result(
    value: object,
    expected_mode: str,
    expected_width: int,
    expected_height: int,
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
    if value["backend"] not in {"webui", "diffusers"} or value["mode"] != expected_mode:
        raise ArtifactError("invalid_backend_result", "Backend or mode does not match the request.")
    if value["width"] != expected_width or value["height"] != expected_height:
        raise ArtifactError("invalid_backend_result", "Backend dimensions do not match the request.")
    if not isinstance(value["path"], str) or not value["path"]:
        raise ArtifactError("invalid_backend_result", "Backend path must be non-empty.")
    if isinstance(value["seed"], bool) or not isinstance(value["seed"], (int, type(None))):
        raise ArtifactError("invalid_backend_result", "Backend seed must be an integer or null.")
    return copy.deepcopy(value)
