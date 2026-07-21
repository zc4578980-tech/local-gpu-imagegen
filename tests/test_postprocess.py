from __future__ import annotations

import hashlib
import os
import subprocess
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

from local_gpu_imagegen.artifacts import validate_png as real_validate_png  # noqa: E402
from local_gpu_imagegen.errors import ArtifactError, AssetEngineError, ValidationError  # noqa: E402
from local_gpu_imagegen.postprocess import RealEsrganAdapter  # noqa: E402


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def write_test_png(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + b"\x20\x40\x80" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(scanlines))
        + _chunk(b"IEND", b"")
    )


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.returncode = 0
        self.stderr = ""
        self.output_width = 8
        self.output_height = 12
        self.write_output = True
        self.raise_timeout = False
        self.output_kind = "png"
        self.create_destination_directory = False

    def __call__(self, args: list[str], **kwargs: object) -> SimpleNamespace:
        self.calls.append((list(args), dict(kwargs)))
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        if self.returncode == 0:
            output = Path(args[args.index("-o") + 1])
            if self.create_destination_directory:
                output.with_name("final-upscaled.png").mkdir()
            if self.write_output:
                if self.output_kind == "empty_directory":
                    output.mkdir()
                else:
                    write_test_png(output, self.output_width, self.output_height)
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr=self.stderr)


class RealEsrganAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.tool_root = root / "realesrgan"
        self.run_root = root / "output" / "runs" / "run-1"
        self.source = self.run_root / "final.png"
        self.destination = self.run_root / "final-upscaled.png"
        self.pending = self.run_root / "final-upscaled.pending.png"
        write_test_png(self.source, 2, 3)
        self.runner = FakeRunner()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def configure_model(self, model: str = "realesrgan-x4plus-anime") -> None:
        (self.tool_root / "models").mkdir(parents=True, exist_ok=True)
        (self.tool_root / "realesrgan-ncnn-vulkan.exe").write_bytes(b"test fixture")
        (self.tool_root / "models" / f"{model}.param").write_bytes(b"test fixture")
        (self.tool_root / "models" / f"{model}.bin").write_bytes(b"test fixture")

    def test_unconfigured_adapter_is_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = RealEsrganAdapter.from_environment()

        self.assertFalse(adapter.is_available())
        self.assertEqual(adapter.available_models(), [])

    def test_requires_executable_and_matching_model_pair(self) -> None:
        (self.tool_root / "models").mkdir(parents=True)
        adapter = RealEsrganAdapter(self.tool_root)
        self.assertFalse(adapter.is_available())

        (self.tool_root / "realesrgan-ncnn-vulkan.exe").write_bytes(b"test fixture")
        (self.tool_root / "models" / "realesrgan-x4plus-anime.param").write_bytes(b"test fixture")
        self.assertEqual(adapter.available_models(), [])

        (self.tool_root / "models" / "realesrgan-x4plus-anime.bin").write_bytes(b"test fixture")
        self.assertEqual(adapter.available_models(), ["realesrgan-x4plus-anime"])

    def test_available_models_are_sorted_and_never_invoke_runner(self) -> None:
        self.configure_model("realesrgan-x4plus-anime")
        self.configure_model("realesr-animevideov3-x4")
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        self.assertEqual(
            adapter.available_models(),
            ["realesr-animevideov3-x4", "realesrgan-x4plus-anime"],
        )
        self.assertEqual(self.runner.calls, [])

    def test_upscale_invokes_ncnn_with_strict_list_and_tool_root_cwd(self) -> None:
        self.configure_model()
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(len(self.runner.calls), 1)
        args, kwargs = self.runner.calls[0]
        self.assertIsInstance(args, list)
        self.assertEqual(
            args,
            [
                str((self.tool_root / "realesrgan-ncnn-vulkan.exe").resolve()),
                "-i",
                str(self.source.resolve()),
                "-o",
                str(self.pending.resolve()),
                "-n",
                "realesrgan-x4plus-anime",
                "-s",
                "4",
                "-f",
                "png",
            ],
        )
        self.assertEqual(Path(str(kwargs["cwd"])), self.tool_root.resolve())
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 900)

    def test_success_validates_4x_png_and_atomically_publishes_metadata(self) -> None:
        self.configure_model()
        original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        result = adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(result["model"], "realesrgan-x4plus-anime")
        self.assertEqual(result["scale"], 4)
        self.assertEqual(result["source"]["path"], str(self.source.resolve()))
        self.assertEqual(result["source"]["sha256"], original_hash)
        self.assertEqual((result["source"]["width"], result["source"]["height"]), (2, 3))
        self.assertEqual(result["output"]["path"], str(self.destination.resolve()))
        self.assertEqual((result["output"]["width"], result["output"]["height"]), (8, 12))
        self.assertEqual(
            result["output"]["sha256"],
            hashlib.sha256(self.destination.read_bytes()).hexdigest(),
        )
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_hash)
        self.assertTrue(self.destination.is_file())
        self.assertFalse(self.pending.exists())

    def test_unsupported_model_is_rejected_before_runner_or_output_work(self) -> None:
        self.configure_model()
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        with self.assertRaises(ValidationError) as raised:
            adapter.upscale(self.source, self.destination, "../../arbitrary-model")

        self.assertEqual(raised.exception.code, "unsupported_postprocess_model")
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.pending.exists())

    def test_missing_requested_model_pair_is_unavailable_before_runner(self) -> None:
        self.configure_model("realesr-animevideov3-x4")
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        with self.assertRaises(AssetEngineError) as raised:
            adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "postprocess_unavailable")
        self.assertEqual(self.runner.calls, [])

    def test_destination_outside_source_run_root_is_rejected_before_runner(self) -> None:
        self.configure_model()
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)
        escaping_destination = self.run_root.parent / "final-upscaled.png"

        with self.assertRaises(AssetEngineError) as raised:
            adapter.upscale(self.source, escaping_destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "path_outside_output_root")
        self.assertEqual(self.runner.calls, [])

    def test_nonzero_exit_is_sanitized_and_removes_pending_residue(self) -> None:
        self.configure_model()
        self.runner.returncode = 9
        self.runner.stderr = "private traceback and local paths"
        self.pending.parent.mkdir(parents=True, exist_ok=True)
        self.pending.write_bytes(b"stale")
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        with self.assertRaises(AssetEngineError) as raised:
            adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "postprocess_failed")
        self.assertEqual(raised.exception.details, {"exit_code": 9})
        self.assertNotIn("private traceback", str(raised.exception))
        self.assertFalse(self.pending.exists())
        self.assertFalse(self.destination.exists())

    def test_wrong_output_dimensions_fail_without_replacing_existing_destination(self) -> None:
        self.configure_model()
        write_test_png(self.destination, 8, 12)
        existing = self.destination.read_bytes()
        self.runner.output_width = 7
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        with self.assertRaises(AssetEngineError) as raised:
            adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "invalid_generated_image")
        self.assertEqual(self.destination.read_bytes(), existing)
        self.assertFalse(self.pending.exists())

    def test_final_validation_failure_restores_existing_destination(self) -> None:
        self.configure_model()
        existing = b"existing destination"
        self.destination.write_bytes(existing)
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)
        validation_count = 0

        def fail_final_validation(path: Path, width: int, height: int) -> dict[str, object]:
            nonlocal validation_count
            validation_count += 1
            if validation_count == 4:
                raise ArtifactError(
                    "invalid_generated_image",
                    "Generated image failed validation after publication.",
                )
            return real_validate_png(path, width, height)

        with patch("local_gpu_imagegen.postprocess.validate_png", side_effect=fail_final_validation):
            with self.assertRaises(AssetEngineError) as raised:
                adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "invalid_generated_image")
        self.assertEqual(self.destination.read_bytes(), existing)
        self.assertFalse(self.pending.exists())

    def test_timeout_is_sanitized_and_removes_pending_residue(self) -> None:
        self.configure_model()
        self.runner.raise_timeout = True
        self.pending.write_bytes(b"stale")
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        with self.assertRaises(AssetEngineError) as raised:
            adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "postprocess_failed")
        self.assertEqual(raised.exception.details, {"reason": "command_timeout"})
        self.assertFalse(self.pending.exists())
        self.assertFalse(self.destination.exists())

    def test_pending_symlink_alias_is_removed_without_deleting_source(self) -> None:
        self.configure_model()
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        try:
            self.pending.symlink_to(self.source)
        except OSError as error:
            self.skipTest(f"Symlink creation is unavailable: {error}")
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        result = adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(result["output"]["path"], str(self.destination.resolve()))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)
        self.assertFalse(self.pending.exists())
        self.assertEqual(len(self.runner.calls), 1)

    def test_directory_shaped_pending_does_not_mask_validation_failure(self) -> None:
        self.configure_model()
        self.runner.output_kind = "empty_directory"
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        with self.assertRaises(AssetEngineError) as raised:
            adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "invalid_generated_image")
        self.assertFalse(self.pending.exists())
        self.assertFalse(self.destination.exists())

    def test_faulty_runner_destination_directory_is_removed_on_failure(self) -> None:
        self.configure_model()
        self.runner.write_output = False
        self.runner.create_destination_directory = True
        adapter = RealEsrganAdapter(self.tool_root, runner=self.runner)

        with self.assertRaises(AssetEngineError) as raised:
            adapter.upscale(self.source, self.destination, "realesrgan-x4plus-anime")

        self.assertEqual(raised.exception.code, "invalid_generated_image")
        self.assertFalse(self.pending.exists())
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
