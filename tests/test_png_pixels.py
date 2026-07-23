from __future__ import annotations

from array import array
import stat
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
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


def _insert_after_ihdr(png: bytes, chunk_type: bytes, data: bytes) -> bytes:
    ihdr_end = len(PNG_SIGNATURE) + 12 + 13
    return png[:ihdr_end] + _chunk(chunk_type, data) + png[ihdr_end:]


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

    def soft_mask_pixels(self, layout: dict[str, object] | None = None) -> bytes:
        layout = layout or approved_layout()
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        width = layout["canvas"]["width"]
        height = layout["canvas"]["height"]
        feather = layout["feather_pixels"]
        assert isinstance(width, int) and isinstance(height, int) and isinstance(feather, int)
        subject_width = subject["width"]
        subject_height = subject["height"]
        values = array("f", [1.0]) * (subject_width * subject_height)

        if feather:
            bounded_x = min(feather, subject_width)
            bounded_y = min(feather, subject_height)
            for distance in range(bounded_x):
                rate = struct.unpack("=f", struct.pack("=f", (distance + 1.0) / feather))[0]
                for y in range(subject_height):
                    offset = y * subject_width + distance
                    values[offset] *= rate
            for distance in range(bounded_x):
                rate = struct.unpack("=f", struct.pack("=f", (distance + 1) / feather))[0]
                column = (-distance) % subject_width
                for y in range(subject_height):
                    offset = y * subject_width + column
                    values[offset] *= rate
            for distance in range(bounded_y):
                rate = struct.unpack("=f", struct.pack("=f", (distance + 1) / feather))[0]
                row_start = distance * subject_width
                for x in range(subject_width):
                    values[row_start + x] *= rate
            for distance in range(bounded_y):
                rate = struct.unpack("=f", struct.pack("=f", (distance + 1) / feather))[0]
                row_start = ((-distance) % subject_height) * subject_width
                for x in range(subject_width):
                    values[row_start + x] *= rate

        saved_values = array("f", (255.0 * value for value in values))
        pixels = bytearray(width * height * 3)
        for local_y in range(subject_height):
            y = subject["y"] + local_y
            for local_x in range(subject_width):
                x = subject["x"] + local_x
                intensity = int(saved_values[local_y * subject_width + local_x])
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes((intensity,)) * 3
        return bytes(pixels)

    def soft_mask(self) -> Path:
        return self.write_png(1280, 720, 3, self.soft_mask_pixels())

    def mask_with_left_leak(self) -> Path:
        pixels = bytearray(self.soft_mask_pixels())
        pixels[(100 * 1280 + 100) * 3 : (100 * 1280 + 100) * 3 + 3] = b"\x01\x01\x01"
        return self.write_png(1280, 720, 3, bytes(pixels))

    def off_center_edge_positions(self, subject: dict[str, int]):
        return {
            "left": lambda distance: (subject["x"] + distance, subject["y"] + 101),
            "right": lambda distance: (
                subject["x"] + subject["width"] - 1 - distance,
                subject["y"] + 103,
            ),
            "top": lambda distance: (subject["x"] + 105, subject["y"] + distance),
            "bottom": lambda distance: (
                subject["x"] + 107,
                subject["y"] + subject["height"] - 1 - distance,
            ),
        }

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

    def test_rgb_transparency_and_invalid_reserved_chunk_bit_fail_closed(self) -> None:
        original = _png_bytes(16, 8, 3, pixel_pattern(3))
        mutations = {
            "rgb transparency": _insert_after_ihdr(original, b"tRNS", b"\x00\x01\x00\x02\x00\x03"),
            "reserved bit": _insert_after_ihdr(original, b"texT", b"invalid reserved bit"),
        }
        for label, contents in mutations.items():
            path = self.new_path()
            path.write_bytes(contents)
            with self.subTest(label=label), self.assertRaisesRegex(
                ArtifactError, "unsupported_two_stage_png|invalid_generated_image"
            ):
                decode_png_pixels(path, 16, 8)

    def test_bounded_reader_rejects_oversize_and_non_file_inputs(self) -> None:
        path = self.write_png(16, 8, 3, pixel_pattern(3))
        with patch("local_gpu_imagegen.png_pixels.MAX_IMAGE_BYTES", path.stat().st_size - 1):
            with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
                decode_png_pixels(path, 16, 8)
        with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
            decode_png_pixels(self.directory, 16, 8)

    def test_bounded_reader_rejects_symlink_or_reparse_input(self) -> None:
        target = self.write_png(16, 8, 3, pixel_pattern(3))
        link = self.directory / "linked.png"
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f"Symlink creation is unavailable: {error}")
        with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
            decode_png_pixels(link, 16, 8)

    def test_bounded_reader_rejects_mocked_windows_reparse_input(self) -> None:
        path = self.write_png(16, 8, 3, pixel_pattern(3))
        path_stat = path.lstat()
        reparse_stat = SimpleNamespace(
            st_mode=path_stat.st_mode,
            st_size=path_stat.st_size,
            st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
        )
        with patch.object(Path, "lstat", return_value=reparse_stat):
            with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
                decode_png_pixels(path, 16, 8)

    def test_bounded_reader_rejects_opened_file_identity_drift(self) -> None:
        path = self.write_png(16, 8, 3, pixel_pattern(3))
        different = self.write_png(16, 8, 4, pixel_pattern(4))
        with patch.object(Path, "lstat", return_value=different.lstat()):
            with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
                decode_png_pixels(path, 16, 8)

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

    def test_protected_comparison_counts_rgba_alpha_changes(self) -> None:
        pixels = bytes((10, 20, 30, 255)) * (1280 * 720)
        base = _TestPngImage(self, 1280, 720, pixels, channels=4)
        final = base.copy()
        final.set_pixel(100, 100, (10, 20, 30, 0))
        result = compare_protected_pixels(base.path, final.path, approved_layout())
        self.assertEqual(result["mismatched_pixels"], 1)
        self.assertEqual(result["copy_mismatched_pixels"], 1)

    def test_soft_mask_accepts_exact_installed_asymmetric_output(self) -> None:
        layout = approved_layout()
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        pixels = self.soft_mask_pixels(layout)

        def value_at(x: int, y: int) -> int:
            return pixels[(y * 1280 + x) * 3]

        center_x = subject["x"] + subject["width"] // 2
        center_y = subject["y"] + subject["height"] // 2
        self.assertEqual(value_at(center_x, subject["y"]), 0)
        self.assertEqual(value_at(subject["x"], center_y), 0)
        self.assertEqual(value_at(subject["x"] + subject["width"] - 1, center_y), 15)
        self.assertEqual(value_at(center_x, subject["y"] + subject["height"] - 1), 15)

        feathered = validate_saved_soft_mask(self.write_png(1280, 720, 3, pixels), layout)
        self.assertEqual(feathered["outside_nonzero_pixels"], 0)
        self.assertGreater(feathered["edge_profiles_checked"], 0)

    def test_soft_mask_accepts_zero_and_one_feather_hard_edges(self) -> None:
        for feather in (0, 1):
            edge_layout = approved_layout()
            edge_layout["feather_pixels"] = feather
            edge_path = self.write_png(1280, 720, 3, self.soft_mask_pixels(edge_layout))
            metadata = validate_saved_soft_mask(edge_path, edge_layout)
            self.assertEqual(metadata["feather_pixels"], feather)

    def test_soft_mask_rejects_outside_leakage(self) -> None:
        with self.assertRaises(ArtifactError) as raised:
            validate_saved_soft_mask(self.mask_with_left_leak(), approved_layout())
        self.assertEqual(raised.exception.code, "invalid_two_stage_mask")
        self.assertEqual(raised.exception.details["reason"], "mask_invariants_failed")
        self.assertEqual(raised.exception.details["outside_nonzero_pixels"], 1)

    def test_hard_mask_requires_positive_strict_interior(self) -> None:
        layout = approved_layout()
        layout["feather_pixels"] = 0
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        pixels = bytearray(1280 * 720 * 3)
        last_x = subject["x"] + subject["width"] - 1
        last_y = subject["y"] + subject["height"] - 1
        for y in range(subject["y"], last_y + 1):
            for x in (subject["x"], last_x):
                offset = (y * 1280 + x) * 3
                pixels[offset : offset + 3] = b"\xff\xff\xff"
        for x in range(subject["x"], last_x + 1):
            for y in (subject["y"], last_y):
                offset = (y * 1280 + x) * 3
                pixels[offset : offset + 3] = b"\xff\xff\xff"
        path = self.write_png(1280, 720, 3, bytes(pixels))
        with self.assertRaisesRegex(ArtifactError, "invalid_two_stage_mask"):
            validate_saved_soft_mask(path, layout)

    def test_soft_mask_rejects_unequal_channels_and_empty_mask(self) -> None:
        layout = approved_layout()
        valid = self.soft_mask_pixels()

        unequal = bytearray(valid)
        unequal[((100 * 1280 + 800) * 3) + 1] ^= 1
        cases = (
            ("unequal channels", unequal, "unequal_rgb_channels"),
            ("empty mask", bytearray(len(valid)), "invalid_feather_direction"),
        )
        for label, pixels, reason in cases:
            with self.subTest(label=label), self.assertRaises(ArtifactError) as raised:
                validate_saved_soft_mask(self.write_png(1280, 720, 3, bytes(pixels)), layout)
            self.assertEqual(raised.exception.code, "invalid_two_stage_mask")
            self.assertEqual(raised.exception.details["reason"], reason)

    def test_soft_mask_rejects_off_center_malformed_ramps_on_all_edges(self) -> None:
        layout = approved_layout()
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        valid = self.soft_mask_pixels()

        for edge, coordinates in self.off_center_edge_positions(subject).items():
            nonmonotonic = bytearray(valid)
            for distance, intensity in ((5, 200), (6, 100)):
                x, y = coordinates(distance)
                offset = (y * 1280 + x) * 3
                nonmonotonic[offset : offset + 3] = bytes((intensity,)) * 3
            with self.subTest(edge=edge), self.assertRaises(ArtifactError) as raised:
                validate_saved_soft_mask(self.write_png(1280, 720, 3, bytes(nonmonotonic)), layout)
            self.assertEqual(raised.exception.code, "invalid_two_stage_mask")
            self.assertEqual(raised.exception.details["reason"], "invalid_feather_direction")

    def test_soft_mask_rejects_monotone_plateau_where_installed_profile_rises(self) -> None:
        layout = approved_layout()
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        valid = self.soft_mask_pixels()

        for edge, coordinates in self.off_center_edge_positions(subject).items():
            plateau = bytearray(valid)
            previous_x, previous_y = coordinates(5)
            plateau_x, plateau_y = coordinates(6)
            previous = valid[(previous_y * 1280 + previous_x) * 3]
            offset = (plateau_y * 1280 + plateau_x) * 3
            plateau[offset : offset + 3] = bytes((previous,)) * 3
            with self.subTest(edge=edge):
                with self.assertRaises(ArtifactError) as raised:
                    validate_saved_soft_mask(self.write_png(1280, 720, 3, bytes(plateau)), layout)
                self.assertEqual(raised.exception.code, "invalid_two_stage_mask")
                self.assertEqual(raised.exception.details["reason"], "invalid_feather_direction")

    def test_soft_mask_rejects_monotone_rise_where_installed_profile_is_flat(self) -> None:
        layout = approved_layout()
        subject = layout["subject_mask_rect"]
        assert isinstance(subject, dict)
        valid = self.soft_mask_pixels()
        flat_transition_starts = {"left": 31, "right": 30, "top": 31, "bottom": 30}

        for edge, coordinates in self.off_center_edge_positions(subject).items():
            rising = bytearray(valid)
            distance = flat_transition_starts[edge]
            x, y = coordinates(distance)
            offset = (y * 1280 + x) * 3
            rising[offset : offset + 3] = b"\xfe\xfe\xfe"
            with self.subTest(edge=edge):
                with self.assertRaises(ArtifactError) as raised:
                    validate_saved_soft_mask(self.write_png(1280, 720, 3, bytes(rising)), layout)
                self.assertEqual(raised.exception.code, "invalid_two_stage_mask")
                self.assertEqual(raised.exception.details["reason"], "invalid_feather_direction")


if __name__ == "__main__":
    unittest.main()
