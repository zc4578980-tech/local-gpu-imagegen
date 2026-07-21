from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from pathlib import Path
from typing import BinaryIO

from .errors import ArtifactError


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_BIT_DEPTHS_BY_COLOR_TYPE = {
    0: frozenset((1, 2, 4, 8, 16)),
    2: frozenset((8, 16)),
    3: frozenset((1, 2, 4, 8)),
    4: frozenset((8, 16)),
    6: frozenset((8, 16)),
}
PNG_CHANNELS_BY_COLOR_TYPE = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
MAX_PNG_FILE_BYTES = 64 * 1024 * 1024
MAX_PNG_CHUNK_BYTES = 32 * 1024 * 1024
MAX_PNG_DECOMPRESSED_BYTES = 128 * 1024 * 1024
ADAM7_PASSES = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


class _PngValidationFailure(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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

    digest = hashlib.sha256()
    try:
        file_size = path.stat().st_size
        if file_size > MAX_PNG_FILE_BYTES:
            raise _PngValidationFailure("png_file_too_large")
        with path.open("rb") as stream:
            width, height = _parse_png(stream, digest, expected_width, expected_height)
    except _PngValidationFailure as error:
        raise _invalid_generated_image(path, error.reason) from error
    except OSError as error:
        raise _invalid_generated_image(path, "unreadable_image") from error
    except (ValueError, struct.error, zlib.error) as error:
        raise _invalid_generated_image(path, "malformed_png") from error

    return {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "width": width,
        "height": height,
        "mime_type": "image/png",
    }


def _parse_png(
    stream: BinaryIO,
    digest: "hashlib._Hash",
    expected_width: int,
    expected_height: int,
) -> tuple[int, int]:
    bytes_read = 0

    def read_exact(length: int) -> bytes:
        nonlocal bytes_read
        if length < 0 or length > MAX_PNG_FILE_BYTES - bytes_read:
            raise _PngValidationFailure("png_file_too_large")
        data = stream.read(length)
        digest.update(data)
        bytes_read += len(data)
        if len(data) != length:
            raise ValueError("truncated PNG data")
        return data

    if read_exact(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
        raise ValueError("missing PNG signature")

    chunk_index = 0
    ihdr_count = 0
    dimensions: tuple[int, int] | None = None
    decompressor: zlib.Decompress | None = None
    decompressed_bytes = 0
    decompression_limit: int | None = None
    saw_iend = False

    while True:
        header = read_exact(8)
        length = struct.unpack(">I", header[:4])[0]
        chunk_type = header[4:]
        if length > MAX_PNG_CHUNK_BYTES:
            raise _PngValidationFailure("png_chunk_too_large")
        if not all(65 <= value <= 90 or 97 <= value <= 122 for value in chunk_type):
            raise ValueError("invalid PNG chunk type")

        data = read_exact(length)
        stored_crc = struct.unpack(">I", read_exact(4))[0]
        calculated_crc = zlib.crc32(data, zlib.crc32(chunk_type)) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            raise ValueError("invalid PNG chunk CRC")

        if chunk_type == b"IHDR":
            ihdr_count += 1
            if chunk_index != 0 or ihdr_count != 1 or length != 13:
                raise ValueError("invalid IHDR")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if width <= 0 or height <= 0:
                raise ValueError("invalid PNG dimensions")
            allowed_bit_depths = PNG_BIT_DEPTHS_BY_COLOR_TYPE.get(color_type)
            if allowed_bit_depths is None or bit_depth not in allowed_bit_depths:
                raise ValueError("invalid PNG color type or bit depth")
            if compression != 0:
                raise ValueError("invalid PNG compression method")
            if filter_method != 0:
                raise ValueError("invalid PNG filter method")
            if interlace not in (0, 1):
                raise ValueError("invalid PNG interlace method")
            if width != expected_width or height != expected_height:
                raise _PngValidationFailure("dimension_mismatch")
            dimensions = (width, height)
            decompression_limit = min(
                _png_scanline_bound(width, height, bit_depth, color_type, interlace),
                MAX_PNG_DECOMPRESSED_BYTES,
            )
        elif chunk_type == b"IDAT":
            if dimensions is None or decompression_limit is None:
                raise ValueError("IDAT precedes IHDR")
            if decompressor is None:
                decompressor = zlib.decompressobj()
            remaining = decompression_limit - decompressed_bytes
            output = decompressor.decompress(data, remaining + 1)
            if len(output) > remaining or decompressor.unconsumed_tail:
                raise _PngValidationFailure("png_decompression_limit_exceeded")
            decompressed_bytes += len(output)
            if decompressor.unused_data:
                raise ValueError("bytes follow IDAT zlib stream")
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("invalid IEND")
            saw_iend = True
            if stream.read(1):
                raise ValueError("bytes follow IEND")
            break

        chunk_index += 1

    if ihdr_count != 1 or dimensions is None:
        raise ValueError("missing IHDR")
    if decompressor is None or decompression_limit is None:
        raise ValueError("missing IDAT")
    if not saw_iend:
        raise ValueError("missing IEND")

    remaining = decompression_limit - decompressed_bytes
    output = decompressor.flush(remaining + 1)
    if len(output) > remaining:
        raise _PngValidationFailure("png_decompression_limit_exceeded")
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("invalid IDAT stream")
    return dimensions


def _png_scanline_bound(width: int, height: int, bit_depth: int, color_type: int, interlace: int) -> int:
    bits_per_pixel = PNG_CHANNELS_BY_COLOR_TYPE[color_type] * bit_depth

    def pass_size(pass_width: int, pass_height: int) -> int:
        if pass_width <= 0 or pass_height <= 0:
            return 0
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        return pass_height * (1 + row_bytes)

    if interlace == 0:
        return pass_size(width, height)

    total = 0
    for start_x, start_y, step_x, step_y in ADAM7_PASSES:
        pass_width = 0 if width <= start_x else (width - start_x + step_x - 1) // step_x
        pass_height = 0 if height <= start_y else (height - start_y + step_y - 1) // step_y
        total += pass_size(pass_width, pass_height)
    return total


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
