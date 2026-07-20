from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


MAX_PREVIEW_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PreviewResult:
    path: Path | None
    mime_type: str | None
    data_base64: str | None
    width: int | None
    height: int | None
    warning: str | None


def create_preview(source: Path, destination: Path) -> PreviewResult:
    if source.resolve() == destination.resolve():
        return _unavailable("preview_unavailable:invalid_destination")

    try:
        from PIL import Image
    except ImportError:
        return _unavailable("preview_unavailable:pillow_missing")

    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = _create_temporary_sibling(destination)
        with Image.open(source) as image:
            image.load()
            source_image = image.copy()
        try:
            for longest_edge, quality in ((768, 88), (640, 80)):
                preview_size = _encode_jpeg(Image, source_image, temporary_path, longest_edge, quality)
                if temporary_path.stat().st_size <= MAX_PREVIEW_BYTES:
                    os.replace(temporary_path, destination)
                    temporary_path = None
                    encoded = base64.b64encode(destination.read_bytes()).decode("ascii")
                    return PreviewResult(
                        destination,
                        "image/jpeg",
                        encoded,
                        preview_size[0],
                        preview_size[1],
                        None,
                    )
        finally:
            source_image.close()
        _remove_preview(destination, source)
        return _unavailable("preview_unavailable:size_limit")
    except Exception:
        _remove_preview(destination, source)
        return _unavailable("preview_unavailable:encoding_failed")
    finally:
        if temporary_path is not None:
            _remove_path(temporary_path)


def _create_temporary_sibling(destination: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        return Path(stream.name)


def _encode_jpeg(
    image_module: object,
    source_image: object,
    destination: Path,
    longest_edge: int,
    quality: int,
) -> tuple[int, int]:
    resized = source_image.copy()
    try:
        resized.thumbnail((longest_edge, longest_edge), image_module.Resampling.LANCZOS)
        converted = resized.convert("RGB")
        try:
            clean = image_module.new("RGB", converted.size)
            try:
                clean.paste(converted)
                clean.save(destination, format="JPEG", quality=quality, optimize=True)
                return clean.size
            finally:
                clean.close()
        finally:
            converted.close()
    finally:
        resized.close()


def _remove_preview(destination: Path, source: Path) -> None:
    try:
        if destination.resolve() != source.resolve():
            _remove_path(destination)
    except OSError:
        pass


def _remove_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _unavailable(warning: str) -> PreviewResult:
    return PreviewResult(None, None, None, None, None, warning)
