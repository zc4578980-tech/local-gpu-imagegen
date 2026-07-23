from __future__ import annotations

import copy
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from .artifacts import (
    MAX_IMAGE_BYTES,
    MAX_PNG_CHUNK_BYTES,
    MAX_PNG_DECOMPRESSED_BYTES,
    PNG_SIGNATURE,
    _read_bounded_regular_file,
)
from .errors import ArtifactError
from .two_stage_layout import validate_two_stage_layout


@dataclass(frozen=True)
class DecodedPng:
    width: int
    height: int
    channels: int
    pixels: bytes


class _PngPixelFailure(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def decode_png_pixels(path: Path, expected_width: int, expected_height: int) -> DecodedPng:
    try:
        data = _read_bounded_regular_file(path, MAX_IMAGE_BYTES)
        ihdr, compressed = _parse_exact_png_chunks(data)
        width, height, bit_depth, color_type, compression, filtering, interlace = ihdr
        if (width, height) != (expected_width, expected_height):
            raise _invalid(path, "dimension_mismatch")
        if bit_depth != 8 or color_type not in {2, 6} or compression != 0 or filtering != 0 or interlace != 0:
            raise ArtifactError(
                "unsupported_two_stage_png",
                "Two-stage pixel verification requires non-interlaced 8-bit RGB or RGBA PNG.",
            )
        channels = 3 if color_type == 2 else 4
        row_size = width * channels
        raw = _bounded_decompress(compressed, height * (row_size + 1))
        rows = _unfilter_rows(raw, width, height, channels)
        return DecodedPng(width, height, channels, b"".join(rows))
    except ArtifactError:
        raise
    except _PngPixelFailure as error:
        raise _invalid(path, error.reason) from error
    except (OverflowError, struct.error, ValueError, zlib.error) as error:
        raise _invalid(path, "malformed_png") from error


def compare_protected_pixels(base_path: Path, final_path: Path, layout: object) -> dict[str, object]:
    normalized = validate_two_stage_layout(layout)
    width = normalized["canvas"]["width"]
    height = normalized["canvas"]["height"]
    base = decode_png_pixels(base_path, width, height)
    final = decode_png_pixels(final_path, width, height)
    if base.channels != final.channels:
        raise ArtifactError("unsupported_two_stage_png", "Stage PNG channel counts differ.")
    subject = normalized["subject_mask_rect"]
    copy_rect = normalized["copy_protected_rect"]
    mismatch = 0
    copy_mismatch = 0
    checked = 0
    for y in range(height):
        for x in range(width):
            outside_subject = not _contains(subject, x, y)
            inside_copy = _contains(copy_rect, x, y)
            if not outside_subject:
                continue
            checked += 1
            changed = _pixel(base, x, y) != _pixel(final, x, y)
            mismatch += int(changed)
            copy_mismatch += int(changed and inside_copy)
    return {
        "protected_rect": copy.deepcopy(copy_rect),
        "checked_pixels": checked,
        "mismatched_pixels": mismatch,
        "copy_mismatched_pixels": copy_mismatch,
    }


def validate_saved_soft_mask(mask_path: Path, layout: object) -> dict[str, object]:
    normalized = validate_two_stage_layout(layout)
    width = normalized["canvas"]["width"]
    height = normalized["canvas"]["height"]
    mask = decode_png_pixels(mask_path, width, height)
    subject = normalized["subject_mask_rect"]
    copy_rect = normalized["copy_protected_rect"]
    outside_nonzero = 0
    copy_nonzero = 0
    interior_positive = 0

    for y in range(height):
        for x in range(width):
            rgb = _pixel(mask, x, y)[:3]
            if rgb[0] != rgb[1] or rgb[1] != rgb[2]:
                raise _invalid_mask(mask_path, "unequal_rgb_channels")
            value = rgb[0]
            inside_subject = _contains(subject, x, y)
            if value and not inside_subject:
                outside_nonzero += 1
            if value and _contains(copy_rect, x, y):
                copy_nonzero += 1
            if not inside_subject:
                continue
            if value and _strictly_inside(subject, x, y):
                interior_positive += 1

    feather = normalized["feather_pixels"]
    edge_profiles_checked = _validate_complete_feather_edges(mask_path, mask, subject, feather)
    if (
        outside_nonzero
        or copy_nonzero
        or interior_positive == 0
    ):
        raise _invalid_mask(
            mask_path,
            "mask_invariants_failed",
            {
                "outside_nonzero_pixels": outside_nonzero,
                "copy_nonzero_pixels": copy_nonzero,
                "interior_positive_pixels": interior_positive,
            },
        )
    return {
        "path": str(mask_path),
        "width": width,
        "height": height,
        "channels": mask.channels,
        "feather_pixels": feather,
        "outside_nonzero_pixels": outside_nonzero,
        "copy_nonzero_pixels": copy_nonzero,
        "interior_positive_pixels": interior_positive,
        "edge_profiles_checked": edge_profiles_checked,
        "feather_monotonic": True,
    }


def _parse_exact_png_chunks(data: bytes) -> tuple[tuple[int, int, int, int, int, int, int], bytes]:
    if not data.startswith(PNG_SIGNATURE):
        raise _PngPixelFailure("missing_png_signature")
    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    ihdr: tuple[int, int, int, int, int, int, int] | None = None
    idat_chunks: list[bytes] = []
    compressed_size = 0
    idat_ended = False
    saw_iend = False
    saw_plte = False

    while offset < len(data):
        if len(data) - offset < 12:
            raise _PngPixelFailure("truncated_png_chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        if length > MAX_PNG_CHUNK_BYTES:
            raise _PngPixelFailure("png_chunk_too_large")
        if not all(65 <= value <= 90 or 97 <= value <= 122 for value in chunk_type):
            raise _PngPixelFailure("invalid_png_chunk_type")
        if not 65 <= chunk_type[2] <= 90:
            raise _PngPixelFailure("invalid_png_reserved_bit")
        chunk_end = offset + length
        crc_end = chunk_end + 4
        if crc_end > len(data):
            raise _PngPixelFailure("truncated_png_chunk")
        chunk_data = data[offset:chunk_end]
        stored_crc = struct.unpack(">I", data[chunk_end:crc_end])[0]
        calculated_crc = zlib.crc32(chunk_data, zlib.crc32(chunk_type)) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            raise _PngPixelFailure("invalid_png_chunk_crc")
        offset = crc_end

        if chunk_type == b"IHDR":
            if chunk_index != 0 or ihdr is not None or length != 13:
                raise _PngPixelFailure("invalid_ihdr")
            ihdr = struct.unpack(">IIBBBBB", chunk_data)
            if ihdr[0] <= 0 or ihdr[1] <= 0:
                raise _PngPixelFailure("invalid_png_dimensions")
        elif chunk_type == b"PLTE":
            if ihdr is None or saw_plte or idat_chunks or length == 0 or length % 3 or length > 768:
                raise _PngPixelFailure("invalid_plte")
            saw_plte = True
        elif chunk_type == b"IDAT":
            if ihdr is None or idat_ended:
                raise _PngPixelFailure("invalid_idat_order")
            compressed_size += length
            if compressed_size > MAX_IMAGE_BYTES:
                raise _PngPixelFailure("png_compressed_data_too_large")
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            if ihdr is None or not idat_chunks or length != 0 or offset != len(data):
                raise _PngPixelFailure("invalid_iend")
            saw_iend = True
            break
        elif chunk_type == b"tRNS":
            raise _PngPixelFailure("unsupported_png_transparency")
        else:
            if ihdr is None or chunk_type[0] & 0x20 == 0:
                raise _PngPixelFailure("unsupported_critical_png_chunk")
            if idat_chunks:
                idat_ended = True
        chunk_index += 1

    if ihdr is None or not idat_chunks or not saw_iend:
        raise _PngPixelFailure("incomplete_png")
    return ihdr, b"".join(idat_chunks)


def _bounded_decompress(compressed: bytes, expected_size: int) -> bytes:
    if expected_size <= 0 or expected_size > MAX_PNG_DECOMPRESSED_BYTES:
        raise _PngPixelFailure("png_decompression_limit_exceeded")
    decompressor = zlib.decompressobj()
    output = decompressor.decompress(compressed, expected_size + 1)
    if len(output) > expected_size or decompressor.unconsumed_tail:
        raise _PngPixelFailure("png_decompression_limit_exceeded")
    output += decompressor.flush(expected_size - len(output) + 1)
    if len(output) != expected_size:
        raise _PngPixelFailure("invalid_decompressed_size")
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise _PngPixelFailure("invalid_idat_stream")
    return output


def _unfilter_rows(raw: bytes, width: int, height: int, channels: int) -> list[bytes]:
    row_size = width * channels
    expected_size = height * (row_size + 1)
    if len(raw) != expected_size:
        raise _PngPixelFailure("invalid_decompressed_size")
    rows: list[bytes] = []
    prior = bytes(row_size)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        filtered = raw[offset + 1 : offset + row_size + 1]
        offset += row_size + 1
        if filter_type > 4:
            raise _PngPixelFailure("unsupported_png_filter")
        row = bytearray(row_size)
        for index, value in enumerate(filtered):
            left = row[index - channels] if index >= channels else 0
            above = prior[index]
            upper_left = prior[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            else:
                predictor = _paeth(left, above, upper_left)
            row[index] = (value + predictor) & 0xFF
        unfiltered = bytes(row)
        rows.append(unfiltered)
        prior = unfiltered
    return rows


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _pixel(image: DecodedPng, x: int, y: int) -> bytes:
    offset = (y * image.width + x) * image.channels
    return image.pixels[offset : offset + image.channels]


def _contains(rect: dict[str, int], x: int, y: int) -> bool:
    return (
        rect["x"] <= x < rect["x"] + rect["width"]
        and rect["y"] <= y < rect["y"] + rect["height"]
    )


def _strictly_inside(rect: dict[str, int], x: int, y: int) -> bool:
    return (
        rect["x"] < x < rect["x"] + rect["width"] - 1
        and rect["y"] < y < rect["y"] + rect["height"] - 1
    )


def _validate_complete_feather_edges(
    mask_path: Path,
    mask: DecodedPng,
    subject: dict[str, int],
    feather: int,
) -> int:
    width = subject["width"]
    height = subject["height"]
    last_x = subject["x"] + subject["width"] - 1
    last_y = subject["y"] + subject["height"] - 1
    rates = tuple(_float32((distance + 1) / feather) for distance in range(feather)) if feather else ()
    checked = 0
    for local_y, y in enumerate(range(subject["y"], last_y + 1)):
        profiles = (
            (
                [_pixel(mask, subject["x"] + distance, y)[0] for distance in range(feather + 1)],
                [_installed_saved_mask_value(distance, local_y, width, height, rates) for distance in range(feather + 1)],
            ),
            (
                [_pixel(mask, last_x - distance, y)[0] for distance in range(feather + 1)],
                [
                    _installed_saved_mask_value(width - 1 - distance, local_y, width, height, rates)
                    for distance in range(feather + 1)
                ],
            ),
        )
        for samples, expected in profiles:
            if not _valid_inward_profile(samples, expected, feather):
                raise _invalid_mask(mask_path, "invalid_feather_direction")
            checked += 1
    for local_x, x in enumerate(range(subject["x"], last_x + 1)):
        profiles = (
            (
                [_pixel(mask, x, subject["y"] + distance)[0] for distance in range(feather + 1)],
                [_installed_saved_mask_value(local_x, distance, width, height, rates) for distance in range(feather + 1)],
            ),
            (
                [_pixel(mask, x, last_y - distance)[0] for distance in range(feather + 1)],
                [
                    _installed_saved_mask_value(local_x, height - 1 - distance, width, height, rates)
                    for distance in range(feather + 1)
                ],
            ),
        )
        for samples, expected in profiles:
            if not _valid_inward_profile(samples, expected, feather):
                raise _invalid_mask(mask_path, "invalid_feather_direction")
            checked += 1
    return checked


def _valid_inward_profile(samples: list[int], expected: list[int], feather: int) -> bool:
    if feather == 0:
        return samples[0] > 0
    return (
        all(left <= right for left, right in zip(samples, samples[1:]))
        and all((sample > 0) == (envelope > 0) for sample, envelope in zip(samples, expected))
        and (samples[0] < samples[-1]) == (expected[0] < expected[-1])
    )


def _installed_saved_mask_value(
    x: int,
    y: int,
    width: int,
    height: int,
    rates: tuple[float, ...],
) -> int:
    value = 1.0
    if x < len(rates):
        value = _float32(value * rates[x])
    right_distance = (-x) % width
    if right_distance < len(rates):
        value = _float32(value * rates[right_distance])
    if y < len(rates):
        value = _float32(value * rates[y])
    bottom_distance = (-y) % height
    if bottom_distance < len(rates):
        value = _float32(value * rates[bottom_distance])
    return int(_float32(255.0 * value))


def _float32(value: float) -> float:
    return struct.unpack("=f", struct.pack("=f", value))[0]


def _invalid(path: Path, reason: str) -> ArtifactError:
    return ArtifactError(
        "invalid_generated_image",
        "Generated image is not a valid PNG with the expected dimensions.",
        {"path": str(path), "reason": reason},
    )


def _invalid_mask(
    path: Path,
    reason: str,
    details: dict[str, object] | None = None,
) -> ArtifactError:
    return ArtifactError(
        "invalid_two_stage_mask",
        "Saved two-stage soft mask does not match the approved layout.",
        {"path": str(path), "reason": reason, **(details or {})},
    )
