from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .errors import ArtifactError


def ensure_within(root: Path, candidate: Path) -> Path:
    """Resolve an artifact path and reject anything outside its output root."""
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ArtifactError(
            "path_outside_output_root",
            "Artifact path escapes the configured output root.",
            {"path": str(resolved)},
        )
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_json_serializable(value: object) -> None:
    _serialize_json(value)


def _serialize_json(value: object) -> str:
    try:
        return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    except (TypeError, ValueError, RecursionError) as error:
        raise ArtifactError(
            "invalid_manifest_json",
            "Manifest values must be recursively JSON serializable.",
            {"error_type": type(error).__name__},
        ) from error


def atomic_write_json(path: Path, value: dict[str, object]) -> None:
    """Replace a JSON document without exposing a partially written target."""
    serialized = _serialize_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temp_path.write_text(serialized, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
