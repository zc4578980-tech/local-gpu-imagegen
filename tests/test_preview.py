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


def make_png(width: int = 2, height: int = 1) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + b"\x20\x40\x60" * width for _ in range(height))
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

    def test_rejects_bytes_after_iend(self) -> None:
        self.assert_invalid(make_png() + b"trailing")


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
