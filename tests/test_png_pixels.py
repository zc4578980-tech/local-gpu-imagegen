from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ArtifactError  # noqa: E402
from local_gpu_imagegen.png_pixels import (  # noqa: E402
    compare_protected_pixels,
    decode_png_pixels,
    validate_saved_soft_mask,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def approved_layout(*, width: int = 1280, height: int = 720) -> dict[str, object]:
    return {
        "mode": "copy-subject-two-stage-v1",
        "canvas": {"width": width, "height": height},
        "copy_protected_rect": {"x": 0, "y": 0, "width": 576, "height": height},
        "subject_mask_rect": {"x": 720, "y": 24, "width": 512, "height": 672},
        "feather_pixels": 32,
        "vae_grow_mask_by": 8,
    }


def pixel_pattern(channels: int) -> bytes:
    return bytes(
        (x * 17 + y * 31 + channel * 47) % 256
        for y in range(8)
        for x in range(16)
        for channel in range(channels)
    )


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(chunk_type)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


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


def _filtered_scanlines(
    width: int,
    height: int,
    channels: int,
    pixels: bytes,
    filter_type: int,
) -> bytes:
    row_size = width * channels
    rows: list[bytes] = []
    prior = bytes(row_size)
    for y in range(height):
        row = pixels[y * row_size : (y + 1) * row_size]
        filtered = bytearray(row_size)
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            above = prior[index]
            upper_left = prior[index - channels] if index >= channels else 0
            predictors = (
                0,
                left,
                above,
                (left + above) // 2,
                _paeth(left, above, upper_left),
            )
            filtered[index] = (value - predictors[filter_type]) & 0xFF
        rows.append(bytes((filter_type,)) + bytes(filtered))
        prior = row
    return b"".join(rows)


def _png_bytes(
    width: int,
    height: int,
    channels: int,
    pixels: bytes,
    *,
    filter_type: int = 0,
    color_type: int | None = None,
    interlace: int = 0,
    raw: bytes | None = None,
) -> bytes:
    resolved_color_type = color_type if color_type is not None else {3: 2, 4: 6}[channels]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, resolved_color_type, 0, 0, interlace)
    scanlines = raw if raw is not None else _filtered_scanlines(width, height, channels, pixels, filter_type)
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(scanlines)) + _chunk(b"IEND", b"")


class _TestPngImage:
    def __init__(
        self,
        test_case: "PngPixelTests",
        width: int,
        height: int,
        pixels: bytes,
        *,
        channels: int = 3,
    ) -> None:
        self.test_case = test_case
        self.width = width
        self.height = height
        self.channels = channels
        self.pixels = bytearray(pixels)
        self._path = test_case.new_path()

    @property
    def path(self) -> Path:
        self._path.write_bytes(_png_bytes(self.width, self.height, self.channels, bytes(self.pixels)))
        return self._path

    def copy(self) -> "_TestPngImage":
        return _TestPngImage(
            self.test_case,
            self.width,
            self.height,
            bytes(self.pixels),
            channels=self.channels,
        )

    def set_pixel(self, x: int, y: int, value: tuple[int, ...]) -> None:
        offset = (y * self.width + x) * self.channels
        self.pixels[offset : offset + self.channels] = bytes(value)


class PngPixelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.path_number = 0

    def new_path(self) -> Path:
        self.path_number += 1
        return self.directory / f"fixture-{self.path_number:02d}.png"

    def write_png(
        self,
        width: int,
        height: int,
        channels: int,
        pixels: bytes,
        *,
        filter_type: int = 0,
    ) -> Path:
        path = self.new_path()
        path.write_bytes(_png_bytes(width, height, channels, pixels, filter_type=filter_type))
        return path

    def fixture(self, mutation: str) -> Path:
        path = self.new_path()
        pixels = pixel_pattern(3)
        if mutation == "indexed":
            contents = _png_bytes(16, 8, 1, bytes(range(128)), color_type=3)
        elif mutation == "grayscale":
            contents = _png_bytes(16, 8, 1, bytes(range(128)), color_type=0)
        elif mutation == "interlaced":
            contents = _png_bytes(16, 8, 3, pixels, interlace=1)
        elif mutation == "truncated":
            contents = _png_bytes(16, 8, 3, pixels)[:-4]
        elif mutation == "bad-filter":
            row_size = 16 * 3
            raw = b"\x05" + pixels[:row_size] + _filtered_scanlines(16, 7, 3, pixels[row_size:], 0)
            contents = _png_bytes(16, 8, 3, pixels, raw=raw)
        elif mutation == "overflow":
            contents = _png_bytes(16, 8, 3, pixels, raw=b"\x00" * 16_384)
        else:  # pragma: no cover - test fixture guard
            raise AssertionError(f"unknown mutation: {mutation}")
        path.write_bytes(contents)
        return path

    def solid_image(
        self,
        width: int,
        height: int,
        value: tuple[int, int, int],
    ) -> _TestPngImage:
        return _TestPngImage(self, width, height, bytes(value) * (width * height))

    def soft_mask_pixels(self) -> bytes:
        layout = approved_layout()
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        width = layout["canvas"]["width"]
        height = layout["canvas"]["height"]
        feather = layout["feather_pixels"]
        assert isinstance(width, int) and isinstance(height, int) and isinstance(feather, int)
        pixels = bytearray(width * height * 3)
        for y in range(subject["y"], subject["y"] + subject["height"]):
            for x in range(subject["x"], subject["x"] + subject["width"]):
                distance = min(
                    x - subject["x"],
                    subject["x"] + subject["width"] - 1 - x,
                    y - subject["y"],
                    subject["y"] + subject["height"] - 1 - y,
                )
                intensity = min(255, distance * 255 // feather)
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes((intensity,)) * 3
        return bytes(pixels)

    def soft_mask(self) -> Path:
        return self.write_png(1280, 720, 3, self.soft_mask_pixels())

    def mask_with_left_leak(self) -> Path:
        pixels = bytearray(self.soft_mask_pixels())
        pixels[(100 * 1280 + 100) * 3 : (100 * 1280 + 100) * 3 + 3] = b"\x01\x01\x01"
        return self.write_png(1280, 720, 3, bytes(pixels))

    def test_rgb_and_rgba_round_trip_without_pillow(self) -> None:
        for channels in (3, 4):
            path = self.write_png(16, 8, channels, pixel_pattern(channels))
            decoded = decode_png_pixels(path, 16, 8)
            self.assertEqual((decoded.width, decoded.height, decoded.channels), (16, 8, channels))
            self.assertEqual(decoded.pixels, pixel_pattern(channels))

    def test_all_png_filters_decode(self) -> None:
        for filter_type in range(5):
            path = self.write_png(16, 8, 3, pixel_pattern(3), filter_type=filter_type)
            self.assertEqual(decode_png_pixels(path, 16, 8).pixels, pixel_pattern(3))

    def test_unsupported_or_malformed_png_fails_closed(self) -> None:
        for mutation in ("indexed", "grayscale", "interlaced", "truncated", "bad-filter", "overflow"):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                ArtifactError, "unsupported_two_stage_png|invalid_generated_image"
            ):
                decode_png_pixels(self.fixture(mutation), 16, 8)

    def test_bounded_reader_rejects_oversize_and_non_file_inputs(self) -> None:
        path = self.write_png(16, 8, 3, pixel_pattern(3))
        with patch("local_gpu_imagegen.png_pixels.MAX_IMAGE_BYTES", path.stat().st_size - 1):
            with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
                decode_png_pixels(path, 16, 8)
        with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
            decode_png_pixels(self.directory, 16, 8)

    def test_protected_comparison_detects_one_changed_pixel(self) -> None:
        layout = approved_layout(width=1280, height=720)
        base = self.solid_image(1280, 720, (10, 20, 30))
        final = base.copy()
        final.set_pixel(800, 100, (200, 100, 50))
        passing = compare_protected_pixels(base.path, final.path, layout)
        self.assertEqual(passing["mismatched_pixels"], 0)
        final.set_pixel(100, 100, (200, 100, 50))
        failing = compare_protected_pixels(base.path, final.path, layout)
        self.assertEqual(failing["mismatched_pixels"], 1)
        self.assertEqual(failing["copy_mismatched_pixels"], 1)

    def test_protected_comparison_rejects_channel_mismatch(self) -> None:
        base = self.solid_image(1280, 720, (10, 20, 30))
        final = _TestPngImage(self, 1280, 720, bytes((10, 20, 30, 255)) * (1280 * 720), channels=4)
        with self.assertRaisesRegex(ArtifactError, "unsupported_two_stage_png"):
            compare_protected_pixels(base.path, final.path, approved_layout())

    def test_soft_mask_must_be_zero_outside_and_feather_inward(self) -> None:
        metadata = validate_saved_soft_mask(self.soft_mask(), approved_layout())
        self.assertEqual(metadata["outside_nonzero_pixels"], 0)
        with self.assertRaisesRegex(ArtifactError, "invalid_two_stage_mask"):
            validate_saved_soft_mask(self.mask_with_left_leak(), approved_layout())

    def test_soft_mask_rejects_channel_border_interior_and_feather_violations(self) -> None:
        layout = approved_layout()
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        valid = self.soft_mask_pixels()
        cases: list[tuple[str, bytearray]] = []

        unequal = bytearray(valid)
        unequal[((100 * 1280 + 800) * 3) + 1] ^= 1
        cases.append(("unequal channels", unequal))

        border = bytearray(valid)
        border_offset = ((subject["y"] + subject["height"] // 2) * 1280 + subject["x"]) * 3
        border[border_offset : border_offset + 3] = b"\x01\x01\x01"
        cases.append(("nonzero border", border))

        cases.append(("empty interior", bytearray(len(valid))))

        nonmonotonic = bytearray(valid)
        sample_y = subject["y"] + subject["height"] // 2
        for distance, intensity in ((1, 200), (2, 100)):
            offset = (sample_y * 1280 + subject["x"] + distance) * 3
            nonmonotonic[offset : offset + 3] = bytes((intensity,)) * 3
        cases.append(("nonmonotonic feather", nonmonotonic))

        for label, pixels in cases:
            with self.subTest(label=label), self.assertRaisesRegex(ArtifactError, "invalid_two_stage_mask"):
                validate_saved_soft_mask(self.write_png(1280, 720, 3, bytes(pixels)), layout)


if __name__ == "__main__":
    unittest.main()
