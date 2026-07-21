from __future__ import annotations

import builtins
import hashlib
import importlib.util
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def make_png(
    width: int = 2,
    height: int = 1,
    *,
    bit_depth: int = 8,
    color_type: int = 2,
    compression: int = 0,
    filter_method: int = 0,
    interlace: int = 0,
) -> bytes:
    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        bit_depth,
        color_type,
        compression,
        filter_method,
        interlace,
    )
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 1)
    bits_per_pixel = channels * bit_depth

    def pass_data(pass_width: int, pass_height: int) -> bytes:
        if pass_width <= 0 or pass_height <= 0:
            return b""
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        return b"".join(b"\x00" + b"\x00" * row_bytes for _ in range(pass_height))

    if interlace == 0:
        scanlines = pass_data(width, height)
    else:
        scanlines = b""
        for start_x, start_y, step_x, step_y in (
            (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
            (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
        ):
            pass_width = 0 if width <= start_x else (width - start_x + step_x - 1) // step_x
            pass_height = 0 if height <= start_y else (height - start_y + step_y - 1) // step_y
            scanlines += pass_data(pass_width, pass_height)
    return (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(scanlines))
        + png_chunk(b"IEND", b"")
    )


def corrupt_chunk_crc(png: bytes, chunk_type: bytes) -> bytes:
    offset = len(PNG_SIGNATURE)
    while offset < len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        current_type = png[offset + 4 : offset + 8]
        crc_offset = offset + 8 + length
        if current_type == chunk_type:
            corrupted = bytearray(png)
            corrupted[crc_offset] ^= 0x01
            return bytes(corrupted)
        offset = crc_offset + 4
    raise AssertionError(f"chunk not found: {chunk_type!r}")


class PngValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "generated.png"

    def validate_png(self, expected_width: int = 2, expected_height: int = 1) -> dict[str, object]:
        try:
            from local_gpu_imagegen.artifacts import validate_png
        except ImportError as error:
            self.fail(f"validate_png is unavailable: {error}")
        return validate_png(self.path, expected_width, expected_height)

    def assert_invalid(self, contents: bytes, expected_width: int = 2, expected_height: int = 1) -> None:
        self.path.write_bytes(contents)
        try:
            from local_gpu_imagegen.errors import ArtifactError
        except ImportError as error:  # pragma: no cover - existing project API
            self.fail(f"ArtifactError is unavailable: {error}")
        with self.assertRaisesRegex(ArtifactError, "invalid_generated_image"):
            self.validate_png(expected_width, expected_height)

    def test_valid_png_returns_trusted_metadata(self) -> None:
        contents = make_png()
        self.path.write_bytes(contents)

        metadata = self.validate_png()

        self.assertEqual(
            metadata,
            {
                "path": str(self.path),
                "sha256": hashlib.sha256(contents).hexdigest(),
                "width": 2,
                "height": 1,
                "mime_type": "image/png",
            },
        )

    def test_rejects_corrupt_chunk_crc(self) -> None:
        self.assert_invalid(corrupt_chunk_crc(make_png(), b"IDAT"))

    def test_rejects_truncated_iend_chunk(self) -> None:
        self.assert_invalid(make_png()[:-4])

    def test_rejects_dimension_mismatch(self) -> None:
        self.assert_invalid(make_png(), expected_width=3)

    def test_rejects_non_positive_expected_dimensions(self) -> None:
        self.assert_invalid(make_png(), expected_width=0)

    def test_rejects_duplicate_ihdr(self) -> None:
        contents = make_png()
        ihdr_end = len(PNG_SIGNATURE) + 12 + 13
        duplicate_ihdr = contents[:ihdr_end] + contents[len(PNG_SIGNATURE) : ihdr_end] + contents[ihdr_end:]
        self.assert_invalid(duplicate_ihdr)

    def test_rejects_non_decompressible_idat(self) -> None:
        ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0)
        contents = (
            PNG_SIGNATURE
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", b"not-zlib-data")
            + png_chunk(b"IEND", b"")
        )
        self.assert_invalid(contents)

    def test_rejects_idat_expansion_beyond_ihdr_scanline_bound(self) -> None:
        ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0)
        contents = (
            PNG_SIGNATURE
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(b"\x00" * 16_384))
            + png_chunk(b"IEND", b"")
        )
        self.path.write_bytes(contents)
        from local_gpu_imagegen.errors import ArtifactError

        with self.assertRaises(ArtifactError) as raised:
            self.validate_png()

        self.assertEqual(raised.exception.code, "invalid_generated_image")
        self.assertEqual(raised.exception.details["reason"], "png_decompression_limit_exceeded")

    def test_validation_streams_input_instead_of_reading_the_whole_file(self) -> None:
        self.path.write_bytes(make_png())
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
            metadata = self.validate_png()
        self.assertEqual((metadata["width"], metadata["height"]), (2, 1))

    def test_rejects_input_larger_than_configured_file_limit(self) -> None:
        contents = make_png()
        self.path.write_bytes(contents)
        with patch("local_gpu_imagegen.artifacts.MAX_PNG_FILE_BYTES", len(contents) - 1, create=True):
            from local_gpu_imagegen.errors import ArtifactError

            with self.assertRaises(ArtifactError) as raised:
                self.validate_png()
        self.assertEqual(raised.exception.details["reason"], "png_file_too_large")

    def test_rejects_chunk_larger_than_configured_chunk_limit(self) -> None:
        self.path.write_bytes(make_png())
        with patch("local_gpu_imagegen.artifacts.MAX_PNG_CHUNK_BYTES", 12):
            from local_gpu_imagegen.errors import ArtifactError

            with self.assertRaises(ArtifactError) as raised:
                self.validate_png()
        self.assertEqual(raised.exception.details["reason"], "png_chunk_too_large")

    def test_rejects_bytes_after_iend(self) -> None:
        self.assert_invalid(make_png() + b"trailing")

    def test_rejects_invalid_ihdr_format_fields(self) -> None:
        invalid_fields = (
            ("invalid color type", {"color_type": 1}),
            ("invalid bit depth for color type", {"color_type": 2, "bit_depth": 4}),
            ("invalid compression method", {"compression": 1}),
            ("invalid filter method", {"filter_method": 1}),
            ("invalid interlace method", {"interlace": 2}),
        )

        for label, fields in invalid_fields:
            with self.subTest(label=label):
                self.assert_invalid(make_png(**fields))

    def test_accepts_allowed_ihdr_color_type_and_bit_depth_combinations(self) -> None:
        allowed_depths = {
            0: (1, 2, 4, 8, 16),
            2: (8, 16),
            3: (1, 2, 4, 8),
            4: (8, 16),
            6: (8, 16),
        }

        for color_type, bit_depths in allowed_depths.items():
            for bit_depth in bit_depths:
                with self.subTest(color_type=color_type, bit_depth=bit_depth):
                    self.path.write_bytes(make_png(color_type=color_type, bit_depth=bit_depth, interlace=1))
                    metadata = self.validate_png()
                    self.assertEqual((metadata["width"], metadata["height"]), (2, 1))


class PreviewWithoutPillowTests(unittest.TestCase):
    def test_missing_pillow_returns_warning_and_preserves_source(self) -> None:
        try:
            from local_gpu_imagegen.preview import create_preview
        except ImportError as error:
            self.fail(f"create_preview is unavailable: {error}")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full.png"
            destination = Path(directory) / "preview.jpg"
            original = make_png()
            source.write_bytes(original)
            original_import = builtins.__import__

            def import_without_pillow(name: str, *args: object, **kwargs: object) -> object:
                if name == "PIL" or name.startswith("PIL."):
                    raise ImportError("Pillow unavailable for test")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=import_without_pillow):
                result = create_preview(source, destination)

            self.assertEqual(result.warning, "preview_unavailable:pillow_missing")
            self.assertIsNone(result.path)
            self.assertFalse(destination.exists())
            self.assertEqual(source.read_bytes(), original)

    def test_same_source_and_destination_is_rejected_before_pillow_import(self) -> None:
        from local_gpu_imagegen.preview import create_preview

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full.png"
            original = make_png()
            source.write_bytes(original)

            with patch("builtins.__import__", side_effect=ImportError("Pillow unavailable for test")):
                result = create_preview(source, source)

            self.assertEqual(result.warning, "preview_unavailable:invalid_destination")
            self.assertEqual(source.read_bytes(), original)


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow not installed")
class PreviewEncodingTests(unittest.TestCase):
    def test_creates_bounded_jpeg_with_inline_data(self) -> None:
        from PIL import Image
        try:
            from local_gpu_imagegen.preview import create_preview
        except ImportError as error:
            self.fail(f"create_preview is unavailable: {error}")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full.png"
            destination = Path(directory) / "nested" / "preview.jpg"
            Image.new("RGBA", (1200, 600), (30, 80, 140, 128)).save(source, format="PNG")
            original = source.read_bytes()

            result = create_preview(source, destination)

            self.assertEqual(result.mime_type, "image/jpeg")
            self.assertLessEqual(max(result.width, result.height), 768)
            self.assertLessEqual(result.path.stat().st_size, 1024 * 1024)
            self.assertIsNotNone(result.data_base64)
            self.assertEqual(source.read_bytes(), original)
            with Image.open(result.path) as preview:
                self.assertEqual(preview.mode, "RGB")
                self.assertNotIn("exif", preview.info)

    def test_existing_hard_link_destination_is_replaced_without_changing_source(self) -> None:
        from PIL import Image
        from local_gpu_imagegen.preview import create_preview

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full.png"
            destination = Path(directory) / "preview.jpg"
            Image.new("RGB", (1000, 500), (40, 90, 150)).save(source, format="PNG")
            original = source.read_bytes()
            original_hash = hashlib.sha256(original).hexdigest()
            os.link(source, destination)
            self.assertTrue(os.path.samefile(source, destination))

            result = create_preview(source, destination)

            self.assertIsNone(result.warning)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(os.path.samefile(source, destination))
            with Image.open(destination) as preview:
                self.assertEqual(preview.format, "JPEG")

    def test_retries_once_with_smaller_settings_after_first_size_limit(self) -> None:
        from PIL import Image
        from local_gpu_imagegen.preview import MAX_PREVIEW_BYTES, create_preview

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full.png"
            destination = Path(directory) / "preview.jpg"
            Image.new("RGB", (1000, 500), (40, 90, 150)).save(source, format="PNG")
            original = source.read_bytes()
            attempts: list[tuple[Path, int, int]] = []

            def deterministic_encode(
                image_module: object,
                source_image: object,
                attempt_path: Path,
                longest_edge: int,
                quality: int,
            ) -> tuple[int, int]:
                attempts.append((attempt_path, longest_edge, quality))
                if len(attempts) == 1:
                    attempt_path.write_bytes(b"x" * (MAX_PREVIEW_BYTES + 1))
                    return (768, 384)
                attempt_path.write_bytes(b"bounded-jpeg")
                return (640, 320)

            with patch("local_gpu_imagegen.preview._encode_jpeg", side_effect=deterministic_encode):
                result = create_preview(source, destination)

            self.assertEqual([(edge, quality) for _, edge, quality in attempts], [(768, 88), (640, 80)])
            self.assertTrue(all(path != destination for path, _, _ in attempts))
            self.assertEqual(result.path, destination)
            self.assertEqual((result.width, result.height), (640, 320))
            self.assertEqual(destination.read_bytes(), b"bounded-jpeg")
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(list(destination.parent.glob(f".{destination.name}.*.tmp")))

    def test_two_oversize_attempts_remove_preview_and_temporary_file(self) -> None:
        from PIL import Image
        from local_gpu_imagegen.preview import MAX_PREVIEW_BYTES, create_preview

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full.png"
            destination = Path(directory) / "preview.jpg"
            Image.new("RGB", (1000, 500), (40, 90, 150)).save(source, format="PNG")
            original = source.read_bytes()
            attempts: list[tuple[Path, int, int]] = []

            def deterministic_encode(
                image_module: object,
                source_image: object,
                attempt_path: Path,
                longest_edge: int,
                quality: int,
            ) -> tuple[int, int]:
                attempts.append((attempt_path, longest_edge, quality))
                attempt_path.write_bytes(b"x" * (MAX_PREVIEW_BYTES + 1))
                return (longest_edge, longest_edge // 2)

            with patch("local_gpu_imagegen.preview._encode_jpeg", side_effect=deterministic_encode):
                result = create_preview(source, destination)

            self.assertEqual([(edge, quality) for _, edge, quality in attempts], [(768, 88), (640, 80)])
            self.assertTrue(all(path != destination for path, _, _ in attempts))
            self.assertEqual(result.warning, "preview_unavailable:size_limit")
            self.assertFalse(destination.exists())
            self.assertFalse(list(destination.parent.glob(f".{destination.name}.*.tmp")))
            self.assertEqual(source.read_bytes(), original)

    def test_encoding_failure_preserves_full_source_and_removes_preview(self) -> None:
        try:
            from local_gpu_imagegen.preview import create_preview
        except ImportError as error:
            self.fail(f"create_preview is unavailable: {error}")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "full.png"
            destination = Path(directory) / "preview.jpg"
            original = b"not an image"
            source.write_bytes(original)
            destination.write_bytes(b"stale preview")

            result = create_preview(source, destination)

            self.assertIsNotNone(result.warning)
            self.assertFalse(destination.exists())
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
