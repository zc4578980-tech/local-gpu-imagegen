from __future__ import annotations

import os
import secrets
import stat
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path

from .artifacts import MAX_PNG_FILE_BYTES, PNG_SIGNATURE, ensure_within, validate_png
from .errors import ArtifactError, AssetEngineError, ValidationError


SUPPORTED_MODELS = frozenset({"realesrgan-x4plus-anime", "realesr-animevideov3-x4"})
EXECUTABLE_NAME = "realesrgan-ncnn-vulkan.exe"
OUTPUT_NAME = "final-upscaled.png"
PENDING_OUTPUT_NAME = "final-upscaled.pending.png"
UPSCALE_SCALE = 4
COMMAND_TIMEOUT_SECONDS = 900
POSTPROCESS_CLEANUP_WARNING = "postprocess_cleanup_failed"

ProcessRunner = Callable[..., object]


class RealEsrganAdapter:
    def __init__(self, tool_root: Path | None, runner: ProcessRunner | None = None) -> None:
        self.tool_root = Path(tool_root) if tool_root is not None else None
        self.runner = runner or subprocess.run

    @classmethod
    def from_environment(cls) -> "RealEsrganAdapter":
        value = os.environ.get("LOCAL_GPU_IMAGEGEN_REALESRGAN_DIR")
        return cls(Path(value)) if value else cls(None)

    def is_available(self) -> bool:
        return bool(self.available_models())

    def available_models(self) -> list[str]:
        if self.tool_root is None:
            return []
        try:
            root = self.tool_root.resolve()
        except OSError:
            return []
        if _controlled_file(root, root / EXECUTABLE_NAME) is None:
            return []
        return sorted(model for model in SUPPORTED_MODELS if self._model_is_available(model))

    def upscale(self, source: Path, destination: Path, model: str) -> dict[str, object]:
        if model not in SUPPORTED_MODELS:
            raise ValidationError(
                "unsupported_postprocess_model",
                "Postprocess model is not supported.",
                {"model": model, "allowed": sorted(SUPPORTED_MODELS)},
            )
        tool_root, executable = self._required_tool(model)
        source_path, destination_path, pending_path = self._artifact_paths(source, destination)
        destination_existed = _lexical_entry_exists(destination_path)
        backup_path = destination_path.with_name(f".final-upscaled.rollback.{secrets.token_hex(8)}.png")
        backup_created = False
        source_width, source_height = _validated_png_dimensions(source_path)
        source_metadata = validate_png(source_path, source_width, source_height)
        command = [
            str(executable),
            "-i",
            str(source_path),
            "-o",
            str(pending_path),
            "-n",
            model,
            "-s",
            str(UPSCALE_SCALE),
            "-f",
            "png",
        ]
        failure: Exception | None = None
        try:
            if not remove_postprocess_artifact(pending_path):
                raise AssetEngineError(
                    "postprocess_failed",
                    "Anime postprocessor could not clean its pending artifact.",
                    "postprocess",
                    {"reason": "cleanup_failed", "cleanup_warning": POSTPROCESS_CLEANUP_WARNING},
                )
            try:
                completed = self.runner(
                    command,
                    cwd=tool_root,
                    shell=False,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=COMMAND_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as error:
                raise AssetEngineError(
                    "postprocess_failed",
                    "Anime postprocessor command timed out.",
                    "postprocess",
                    {"reason": "command_timeout"},
                ) from error
            except OSError as error:
                raise AssetEngineError(
                    "postprocess_failed",
                    "Anime postprocessor could not be started.",
                    "postprocess",
                    {"reason": "launch_failed"},
                ) from error
            return_code = getattr(completed, "returncode", None)
            if type(return_code) is not int or return_code != 0:
                details = {"exit_code": return_code} if type(return_code) is int else {"reason": "invalid_runner_result"}
                raise AssetEngineError(
                    "postprocess_failed",
                    "Anime postprocessor command failed.",
                    "postprocess",
                    details,
                )
            output_metadata = validate_png(
                pending_path,
                source_width * UPSCALE_SCALE,
                source_height * UPSCALE_SCALE,
            )
            if destination_existed:
                os.replace(destination_path, backup_path)
                backup_created = True
            os.replace(pending_path, destination_path)
            output_metadata = validate_png(
                destination_path,
                source_width * UPSCALE_SCALE,
                source_height * UPSCALE_SCALE,
            )
        except Exception as error:
            failure = error

        cleanup_failed = not remove_postprocess_artifact(pending_path)
        if failure is None and backup_created:
            if remove_postprocess_artifact(backup_path):
                backup_created = False
            else:
                cleanup_failed = True
        if failure is not None or cleanup_failed:
            if backup_created:
                if not remove_postprocess_artifact(destination_path):
                    cleanup_failed = True
                try:
                    os.replace(backup_path, destination_path)
                    backup_created = False
                except OSError:
                    cleanup_failed = True
            elif not destination_existed and not remove_postprocess_artifact(destination_path):
                cleanup_failed = True
        if failure is not None:
            raise _sanitized_postprocess_failure(failure, cleanup_failed=cleanup_failed)
        if cleanup_failed:
            raise _sanitized_postprocess_failure(None, cleanup_failed=True)

        source_metadata["path"] = str(source_path)
        output_metadata["path"] = str(destination_path)
        return {
            "type": "anime_upscale",
            "model": model,
            "scale": UPSCALE_SCALE,
            "source": source_metadata,
            "output": output_metadata,
        }

    def _required_tool(self, model: str) -> tuple[Path, Path]:
        if self.tool_root is None:
            raise AssetEngineError(
                "postprocess_unavailable",
                "Anime postprocessor is not configured.",
                "postprocess",
            )
        root = self.tool_root.resolve()
        executable = _controlled_file(root, root / EXECUTABLE_NAME)
        model_root = ensure_within(root, root / "models")
        param = _controlled_file(root, model_root / f"{model}.param")
        binary = _controlled_file(root, model_root / f"{model}.bin")
        if executable is None or param is None or binary is None:
            raise AssetEngineError(
                "postprocess_unavailable",
                "Anime postprocessor executable or requested model files are unavailable.",
                "postprocess",
                {"model": model},
            )
        return root, executable

    def _model_is_available(self, model: str) -> bool:
        assert self.tool_root is not None
        try:
            root = self.tool_root.resolve()
            model_root = ensure_within(root, root / "models")
            return all(
                _controlled_file(root, model_root / f"{model}.{suffix}") is not None
                for suffix in ("param", "bin")
            )
        except (ArtifactError, OSError):
            return False

    @staticmethod
    def _artifact_paths(source: Path, destination: Path) -> tuple[Path, Path, Path]:
        source_path = Path(source).resolve()
        run_root = source_path.parent
        destination_path = ensure_within(run_root, Path(destination))
        if destination_path.parent != run_root or destination_path.name != OUTPUT_NAME:
            raise ArtifactError(
                "path_outside_output_root",
                "Postprocess destination must be the run's final-upscaled.png artifact.",
                {"path": str(destination_path)},
            )
        pending_path = run_root / PENDING_OUTPUT_NAME
        return source_path, destination_path, pending_path


def _controlled_file(root: Path, candidate: Path) -> Path | None:
    try:
        resolved = ensure_within(root, candidate)
    except ArtifactError:
        return None
    return resolved if candidate.is_file() and resolved.is_file() else None


def remove_postprocess_artifact(path: Path) -> bool:
    """Remove one exact postprocess artifact entry without following it."""
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    is_reparse = bool(reparse_flag and attributes & reparse_flag)
    try:
        if stat.S_ISLNK(path_stat.st_mode):
            os.unlink(path)
        elif is_reparse and stat.S_ISDIR(path_stat.st_mode):
            os.rmdir(path)
        elif stat.S_ISREG(path_stat.st_mode) or is_reparse:
            os.unlink(path)
        elif stat.S_ISDIR(path_stat.st_mode):
            os.rmdir(path)
        else:
            return False
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _lexical_entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _sanitized_postprocess_failure(
    error: Exception | None,
    *,
    cleanup_failed: bool,
) -> AssetEngineError:
    if isinstance(error, AssetEngineError):
        if cleanup_failed:
            error.details = {**error.details, "cleanup_warning": POSTPROCESS_CLEANUP_WARNING}
        return error
    details: dict[str, object] = {"reason": "artifact_operation_failed"}
    if cleanup_failed:
        details["cleanup_warning"] = POSTPROCESS_CLEANUP_WARNING
    return AssetEngineError(
        "postprocess_failed",
        "Anime postprocessor artifact handling failed.",
        "postprocess",
        details,
    )


def _validated_png_dimensions(path: Path) -> tuple[int, int]:
    try:
        if path.stat().st_size > MAX_PNG_FILE_BYTES:
            raise ArtifactError(
                "invalid_generated_image",
                "Generated image is not a valid PNG with the expected dimensions.",
                {"path": str(path), "reason": "png_file_too_large"},
            )
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as error:
        raise ArtifactError(
            "invalid_generated_image",
            "Generated image is not a valid PNG with the expected dimensions.",
            {"path": str(path), "reason": "unreadable_image"},
        ) from error
    if len(header) != 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ArtifactError(
            "invalid_generated_image",
            "Generated image is not a valid PNG with the expected dimensions.",
            {"path": str(path), "reason": "malformed_png"},
        )
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise ArtifactError(
            "invalid_generated_image",
            "Generated image is not a valid PNG with the expected dimensions.",
            {"path": str(path), "reason": "malformed_png"},
        )
    validate_png(path, width, height)
    return width, height
