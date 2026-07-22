from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .artifacts import sha256_file
from .errors import ConflictError, ValidationError


IDENTITY_STRENGTHS = frozenset({"cryptographic", "backend_binding"})
SUPPORTED_BACKENDS = frozenset({"webui", "comfyui", "diffusers", "filesystem"})
DISCOVERY_REQUIRED = frozenset({
    "backend",
    "endpoint_identity",
    "backend_model_id",
    "format",
    "byte_size",
    "modified_ns",
    "sha256",
    "identity_strength",
    "metadata",
})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_discovery_record(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("invalid_model_identity", "Discovery identity must be an object.")
    missing = sorted(DISCOVERY_REQUIRED - set(value))
    if missing:
        raise ValidationError(
            "invalid_model_identity",
            "Discovery identity is incomplete.",
            {"fields": missing},
        )

    backend = value["backend"]
    if not isinstance(backend, str) or backend not in SUPPORTED_BACKENDS:
        raise ValidationError("invalid_model_identity", "Discovery backend is unsupported.")
    for field in ("endpoint_identity", "backend_model_id", "format"):
        item = value[field]
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(
                "invalid_model_identity",
                f"Discovery {field} must be a non-empty string.",
            )
    for field in ("byte_size", "modified_ns"):
        item = value[field]
        if item is not None and (type(item) is not int or item < 0):
            raise ValidationError(
                "invalid_model_identity",
                f"Discovery {field} must be a non-negative integer or null.",
            )

    strength = value["identity_strength"]
    digest = value["sha256"]
    if strength not in IDENTITY_STRENGTHS:
        raise ValidationError("invalid_model_identity", "Identity strength is unsupported.")
    if strength == "cryptographic" and (
        not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None
    ):
        raise ValidationError(
            "invalid_model_identity",
            "Cryptographic identity requires a lowercase SHA-256 digest.",
        )
    if strength == "backend_binding" and digest is not None:
        raise ValidationError(
            "invalid_model_identity",
            "Backend-binding identity cannot claim a cryptographic digest.",
        )

    metadata = value["metadata"]
    if not isinstance(metadata, dict):
        raise ValidationError("invalid_model_identity", "Discovery metadata must be an object.")
    try:
        json.dumps(metadata, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValidationError(
            "invalid_model_identity",
            "Discovery metadata must be JSON serializable.",
        ) from error

    result = copy.deepcopy(value)
    result["public_evidence_eligible"] = strength == "cryptographic"
    return result


def identity_token(record: dict[str, object]) -> str:
    validated = validate_discovery_record(record)
    boundary = {
        name: validated[name]
        for name in (
            "backend",
            "endpoint_identity",
            "backend_model_id",
            "format",
            "byte_size",
            "modified_ns",
            "sha256",
            "identity_strength",
        )
    }
    if validated["backend"] == "comfyui":
        metadata = validated["metadata"]
        loader_class = metadata.get("loader_class")
        loader_input = metadata.get("loader_input")
        if isinstance(loader_class, str) and isinstance(loader_input, str):
            boundary["loader_identity"] = {
                "loader_class": loader_class,
                "loader_input": loader_input,
            }
    encoded = json.dumps(
        boundary,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "model:" + hashlib.sha256(encoded).hexdigest()


def fingerprint_selected_file(
    path: Path,
    expected: dict[str, object],
) -> dict[str, object]:
    if not isinstance(expected, dict):
        raise ValidationError(
            "invalid_fingerprint_expectation",
            "Fingerprint expectation must be an object.",
        )
    expected_size = expected.get("byte_size")
    expected_modified = expected.get("modified_ns")
    if (
        type(expected_size) is not int
        or expected_size < 0
        or type(expected_modified) is not int
        or expected_modified < 0
    ):
        raise ValidationError(
            "invalid_fingerprint_expectation",
            "Fingerprint expectation requires non-negative byte_size and modified_ns.",
        )

    candidate = Path(path)
    try:
        before = os.stat(candidate, follow_symlinks=False)
        unsafe = _link_like(candidate) or not stat.S_ISREG(before.st_mode)
    except OSError as error:
        raise ValidationError(
            "unsafe_model_path",
            "Selected model must be a readable regular non-link file.",
        ) from error
    if unsafe:
        raise ValidationError(
            "unsafe_model_path",
            "Selected model must be a regular non-link file.",
        )
    if before.st_size != expected_size or before.st_mtime_ns != expected_modified:
        raise ConflictError(
            "model_identity_drifted",
            "Selected model changed after indexing.",
        )

    try:
        digest = sha256_file(candidate)
        after = os.stat(candidate, follow_symlinks=False)
        unsafe_after = _link_like(candidate) or not stat.S_ISREG(after.st_mode)
    except OSError as error:
        raise ConflictError(
            "model_identity_drifted",
            "Selected model changed while hashing.",
        ) from error

    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if unsafe_after or before_identity != after_identity:
        raise ConflictError(
            "model_identity_drifted",
            "Selected model changed while hashing.",
        )
    return {
        "sha256": digest,
        "byte_size": before.st_size,
        "modified_ns": before.st_mtime_ns,
    }


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    path_stat = os.lstat(path)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)
