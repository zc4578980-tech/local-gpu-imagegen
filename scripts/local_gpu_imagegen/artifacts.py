from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from pathlib import Path

from .errors import ArtifactError


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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


def validate_png(path: Path, expected_width: int, expected_height: int) -> dict[str, object]:
    """Validate generated PNG structure without loading an image library."""
    if not _is_positive_dimension(expected_width) or not _is_positive_dimension(expected_height):
        raise _invalid_generated_image(path, "invalid_expected_dimensions")

    try:
        contents = path.read_bytes()
    except OSError as error:
        raise _invalid_generated_image(path, "unreadable_image") from error

    try:
        width, height = _parse_png(contents)
    except (ValueError, struct.error, zlib.error) as error:
        raise _invalid_generated_image(path, "malformed_png") from error

    if width != expected_width or height != expected_height:
        raise _invalid_generated_image(path, "dimension_mismatch")

    return {
        "path": str(path),
        "sha256": hashlib.sha256(contents).hexdigest(),
        "width": width,
        "height": height,
        "mime_type": "image/png",
    }


def _parse_png(contents: bytes) -> tuple[int, int]:
    if not contents.startswith(PNG_SIGNATURE):
        raise ValueError("missing PNG signature")

    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    ihdr_count = 0
    dimensions: tuple[int, int] | None = None
    idat_payloads: list[bytes] = []
    saw_iend = False

    while offset < len(contents):
        if len(contents) - offset < 12:
            raise ValueError("truncated PNG chunk")

        length = struct.unpack(">I", contents[offset : offset + 4])[0]
        chunk_type = contents[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(contents):
            raise ValueError("truncated PNG chunk payload")
        if not all(65 <= value <= 90 or 97 <= value <= 122 for value in chunk_type):
            raise ValueError("invalid PNG chunk type")

        data_start = offset + 8
        data_end = data_start + length
        data = contents[data_start:data_end]
        stored_crc = struct.unpack(">I", contents[data_end:chunk_end])[0]
        calculated_crc = zlib.crc32(data, zlib.crc32(chunk_type)) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            raise ValueError("invalid PNG chunk CRC")

        if chunk_type == b"IHDR":
            ihdr_count += 1
            if chunk_index != 0 or ihdr_count != 1 or length != 13:
                raise ValueError("invalid IHDR")
            width, height = struct.unpack(">II", data[:8])
            if width <= 0 or height <= 0:
                raise ValueError("invalid PNG dimensions")
            dimensions = (width, height)
        elif chunk_type == b"IDAT":
            if dimensions is None:
                raise ValueError("IDAT precedes IHDR")
            idat_payloads.append(data)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("invalid IEND")
            saw_iend = True
            offset = chunk_end
            if offset != len(contents):
                raise ValueError("bytes follow IEND")
            break

        offset = chunk_end
        chunk_index += 1

    if ihdr_count != 1 or dimensions is None:
        raise ValueError("missing IHDR")
    if not idat_payloads:
        raise ValueError("missing IDAT")
    if not saw_iend:
        raise ValueError("missing IEND")

    decompressor = zlib.decompressobj()
    decompressor.decompress(b"".join(idat_payloads))
    decompressor.flush()
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("invalid IDAT stream")
    return dimensions


def _is_positive_dimension(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _invalid_generated_image(path: Path, reason: str) -> ArtifactError:
    return ArtifactError(
        "invalid_generated_image",
        "Generated image is not a valid PNG with the expected dimensions.",
        {"path": str(path), "reason": reason},
    )


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
