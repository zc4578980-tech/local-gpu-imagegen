from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import os
import re
import shutil
import socket
import stat
import tempfile
import urllib.error
import urllib.request
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO, Callable, Iterable
from urllib.parse import urlsplit

from .bootstrap_catalog import MAX_ARTIFACT_BYTES, BootstrapArtifact
from .errors import ArtifactError


MAX_DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_TIMEOUT_SECONDS = 300.0
MAX_ARCHIVE_ENTRIES = 200_000
MAX_ARCHIVE_EXPANDED_BYTES = 20 * 1024 * 1024 * 1024
PY7ZR_VERSION = "1.1.3"
APPROVED_REDIRECT_HOSTS_BY_SOURCE = {
    "github.com": frozenset({
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }),
    "huggingface.co": frozenset({
        "cdn-lfs.hf.co",
        "cdn-lfs-us-1.hf.co",
        "cdn-lfs-eu-1.hf.co",
        "cas-bridge.xethub.hf.co",
    }),
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PLAN_ID = re.compile(r"[0-9a-f]{24}\Z")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    name: str
    kind: str
    uncompressed_bytes: int


@dataclass(frozen=True, slots=True)
class ArchiveInventory:
    entries: tuple[ArchiveEntry, ...]
    entry_count: int
    file_count: int
    directory_count: int
    expanded_bytes: int


def validate_archive_entries(
    entries: Iterable[ArchiveEntry],
    *,
    max_entries: int = MAX_ARCHIVE_ENTRIES,
    max_expanded_bytes: int = MAX_ARCHIVE_EXPANDED_BYTES,
) -> ArchiveInventory:
    if (
        type(max_entries) is not int
        or not 1 <= max_entries <= MAX_ARCHIVE_ENTRIES
        or type(max_expanded_bytes) is not int
        or not 1 <= max_expanded_bytes <= MAX_ARCHIVE_EXPANDED_BYTES
    ):
        raise _unsafe_archive("invalid_limits")

    accepted: list[ArchiveEntry] = []
    destinations: dict[str, str] = {}
    file_destinations: set[str] = set()
    file_count = 0
    directory_count = 0
    expanded_bytes = 0
    for entry in entries:
        if len(accepted) >= max_entries:
            raise _unsafe_archive("entry_count_limit")
        if not isinstance(entry, ArchiveEntry):
            raise _unsafe_archive("invalid_entry_metadata")
        if entry.kind not in {"file", "directory"}:
            raise _unsafe_archive("unsupported_entry_kind", entry.name)
        if (
            type(entry.uncompressed_bytes) is not int
            or entry.uncompressed_bytes < 0
            or (entry.kind == "directory" and entry.uncompressed_bytes != 0)
        ):
            raise _unsafe_archive("invalid_entry_metadata", entry.name)

        destination = _archive_destination_key(entry.name)
        if destination in destinations:
            raise _unsafe_archive("destination_collision", entry.name)
        destinations[destination] = entry.kind
        if entry.kind == "file":
            file_destinations.add(destination)
            file_count += 1
            expanded_bytes += entry.uncompressed_bytes
            if expanded_bytes > max_expanded_bytes:
                raise _unsafe_archive("expanded_bytes_limit", entry.name)
        else:
            directory_count += 1
        accepted.append(entry)

    if not accepted:
        raise _unsafe_archive("empty_archive")

    for destination in destinations:
        parts = destination.split("/")
        for length in range(1, len(parts)):
            if "/".join(parts[:length]) in file_destinations:
                raise _unsafe_archive("file_parent_conflict", destination)

    return ArchiveInventory(
        entries=tuple(accepted),
        entry_count=len(accepted),
        file_count=file_count,
        directory_count=directory_count,
        expanded_bytes=expanded_bytes,
    )


def validate_portable_archive_inventory(
    inventory: ArchiveInventory,
    *,
    expected_root: str,
) -> ArchiveInventory:
    root_key = _archive_destination_key(expected_root)
    if "/" in root_key:
        raise ArtifactError(
            "invalid_portable_layout",
            "Portable archive root must be one safe directory name.",
        )
    destinations = {
        _archive_destination_key(entry.name): entry.kind
        for entry in inventory.entries
    }
    if destinations.get(root_key) != "directory" or any(
        destination != root_key and not destination.startswith(root_key + "/")
        for destination in destinations
    ):
        raise ArtifactError(
            "invalid_portable_layout",
            "Portable archive contains entries outside its exact root.",
        )
    required_files = (
        f"{root_key}/python_embeded/python.exe",
        f"{root_key}/comfyui/main.py",
    )
    missing = [path for path in required_files if destinations.get(path) != "file"]
    if missing:
        raise ArtifactError(
            "invalid_portable_layout",
            "Portable archive is missing required regular-file markers.",
            {"missing": missing},
        )
    return inventory


def safe_extract_portable(
    archive_path: Path,
    install_root: Path,
    *,
    expected_root: str,
    plan_id: str,
    expected_byte_size: int | None = None,
    expected_sha256: str | None = None,
) -> Path:
    try:
        archive = _absolute_without_resolving_links(archive_path)
        root = _absolute_without_resolving_links(install_root)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ArtifactError(
            "invalid_extraction_options",
            "Portable archive and install root paths are invalid.",
        ) from error
    root_key = _archive_destination_key(expected_root)
    if "/" in root_key or not isinstance(plan_id, str) or _PLAN_ID.fullmatch(plan_id) is None:
        raise ArtifactError(
            "invalid_extraction_options",
            "Portable extraction requires one safe root and a 24-character plan ID.",
        )
    if not _is_regular_non_reparse_file(archive):
        raise ArtifactError(
            "invalid_archive_path",
            "Portable archive must be an existing regular non-reparse file.",
        )
    archive_stream = _open_verified_archive(
        archive,
        expected_byte_size=expected_byte_size,
        expected_sha256=expected_sha256,
    )

    try:
        initial_root_guard = _capture_directory_chain(root)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ArtifactError(
                "invalid_install_root",
                "Portable install root could not be created safely.",
            ) from error
        _require_directory_chain(root, initial_root_guard)
        root_guard = _capture_directory_chain(root)
        destination = root / expected_root
        staging = root / f".local-gpu-imagegen-{plan_id}.staging"
        if _path_lexists(destination):
            raise ArtifactError(
                "portable_destination_conflict",
                "Portable destination already exists and will not be overwritten.",
                {"path": str(destination)},
            )
        if _path_lexists(staging):
            raise ArtifactError(
                "portable_staging_conflict",
                "Plan-owned extraction staging path already exists.",
                {"path": str(staging)},
            )

        py7zr = _load_py7zr()
        staging_identity: os.stat_result | None = None
        try:
            _require_directory_chain(root, root_guard)
            staging.mkdir()
            staging_identity = staging.lstat()
            _require_directory_chain(root, root_guard)
            with py7zr.SevenZipFile(
                archive_stream,
                "r",
                max_extract_size=MAX_ARCHIVE_EXPANDED_BYTES,
            ) as archive_reader:
                inventory = validate_archive_entries(
                    _py7zr_archive_entries(archive_reader.list())
                )
                validate_portable_archive_inventory(
                    inventory,
                    expected_root=expected_root,
                )
                _require_directory_chain(root, root_guard)
                archive_reader.extractall(path=staging)
                _require_directory_chain(root, root_guard)

            actual_inventory = _validate_post_extraction(
                inventory,
                staging,
                expected_root=expected_root,
            )
            extracted_root_name = next(
                entry.name
                for entry in actual_inventory.entries
                if _archive_destination_key(entry.name) == root_key
            )
            extracted_root = staging.joinpath(*PurePosixPath(extracted_root_name).parts)
            extracted_identity = extracted_root.lstat()
            _require_directory_chain(root, root_guard)
            extracted_root.rename(destination)
            if not os.path.samestat(extracted_identity, destination.lstat()):
                raise OSError("portable destination identity changed during promotion")
            _require_directory_chain(root, root_guard)
            try:
                staging.rmdir()
            except OSError:
                _remove_owned_directory(staging, staging_identity)
        except BaseException as error:
            _remove_owned_directory(staging, staging_identity)
            if not isinstance(error, Exception):
                raise
            if isinstance(error, ArtifactError):
                raise
            raise ArtifactError(
                "archive_extract_failed",
                "Portable archive extraction failed before destination promotion.",
                {"error_type": type(error).__name__},
            ) from error
        return destination
    finally:
        archive_stream.close()


def _capture_directory_chain(root: Path) -> tuple[tuple[Path, os.stat_result], ...]:
    identities: list[tuple[Path, os.stat_result]] = []
    current = root
    while True:
        if os.path.lexists(current):
            try:
                current_stat = current.lstat()
            except OSError as error:
                raise ArtifactError(
                    "invalid_install_root",
                    "Portable install root ancestry cannot be inspected safely.",
                ) from error
            if not _safe_directory_stat(current_stat):
                raise ArtifactError(
                    "invalid_install_root",
                    "Portable install root ancestry must contain only fixed directories.",
                )
            identities.append((current, current_stat))
        parent = current.parent
        if parent == current:
            break
        current = parent
    return tuple(identities)


def _require_directory_chain(
    root: Path,
    expected: tuple[tuple[Path, os.stat_result], ...],
) -> None:
    try:
        for path, expected_stat in expected:
            current_stat = path.lstat()
            if not _safe_directory_stat(current_stat) or not os.path.samestat(
                expected_stat,
                current_stat,
            ):
                raise OSError("install root ancestry identity changed")
        current = root
        while True:
            if not _safe_directory_stat(current.lstat()):
                raise OSError("install root ancestry became link-like")
            parent = current.parent
            if parent == current:
                break
            current = parent
    except OSError as error:
        raise ArtifactError(
            "invalid_install_root",
            "Portable install root identity changed at a write boundary.",
        ) from error


def _safe_directory_stat(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return (
        stat.S_ISDIR(path_stat.st_mode)
        and not stat.S_ISLNK(path_stat.st_mode)
        and not bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)
    )


def _remove_owned_directory(path: Path, identity: os.stat_result | None) -> None:
    if identity is None:
        return
    try:
        current_stat = path.lstat()
        if _safe_directory_stat(current_stat) and os.path.samestat(identity, current_stat):
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _open_verified_archive(
    archive: Path,
    *,
    expected_byte_size: int | None,
    expected_sha256: str | None,
) -> BinaryIO:
    if (expected_byte_size is None) != (expected_sha256 is None) or (
        expected_byte_size is not None
        and (
            type(expected_byte_size) is not int
            or expected_byte_size <= 0
            or not isinstance(expected_sha256, str)
            or _SHA256.fullmatch(expected_sha256) is None
        )
    ):
        raise ArtifactError(
            "invalid_extraction_options",
            "Frozen archive size and digest must be supplied together.",
        )
    stream: BinaryIO | None = None
    snapshot: BinaryIO | None = None
    try:
        path_stat = archive.lstat()
        stream = archive.open("rb")
        opened_stat = os.fstat(stream.fileno())
        if (
            not os.path.samestat(path_stat, opened_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_nlink != 1
            or (expected_byte_size is not None and opened_stat.st_size != expected_byte_size)
        ):
            raise OSError("archive identity or size changed while opening")
        digest = hashlib.sha256()
        snapshot = tempfile.SpooledTemporaryFile(max_size=1, mode="w+b")
        copied = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            copied += len(block)
            digest.update(block)
            snapshot.write(block)
        if expected_byte_size is not None and copied != expected_byte_size:
            raise OSError("archive byte count does not match frozen artifact")
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise OSError("archive digest does not match frozen artifact")
        snapshot.flush()
        snapshot.seek(0)
        stream.close()
        return snapshot
    except OSError as error:
        for owned_stream in (stream, snapshot):
            if owned_stream is not None:
                try:
                    owned_stream.close()
                except OSError:
                    pass
        raise ArtifactError(
            "invalid_archive_path",
            "Portable archive identity does not match the frozen artifact.",
        ) from error


def _load_py7zr() -> object:
    try:
        installed_version = importlib.metadata.version("py7zr")
        module = importlib.import_module("py7zr")
    except (ImportError, importlib.metadata.PackageNotFoundError) as error:
        raise ArtifactError(
            "extractor_dependency_unavailable",
            f"Portable extraction requires py7zr=={PY7ZR_VERSION}.",
        ) from error
    if installed_version != PY7ZR_VERSION or getattr(module, "__version__", None) != PY7ZR_VERSION:
        raise ArtifactError(
            "extractor_dependency_mismatch",
            f"Portable extraction requires py7zr=={PY7ZR_VERSION}.",
            {"installed_version": installed_version},
        )
    return module


def _py7zr_archive_entries(file_infos: Iterable[object]) -> tuple[ArchiveEntry, ...]:
    entries: list[ArchiveEntry] = []
    for info in file_infos:
        is_symlink = getattr(info, "is_symlink", None)
        is_directory = getattr(info, "is_directory", None)
        is_file = getattr(info, "is_file", None)
        if is_symlink is True:
            kind = "symlink"
        elif is_directory is True and is_file is False:
            kind = "directory"
        elif is_file is True and is_directory is False:
            kind = "file"
        else:
            kind = "unknown"
        entries.append(
            ArchiveEntry(
                name=getattr(info, "filename", None),
                kind=kind,
                uncompressed_bytes=(
                    0 if kind == "directory" else getattr(info, "uncompressed", None)
                ),
            )
        )
    return tuple(entries)


def _filesystem_archive_entries(root: Path) -> tuple[ArchiveEntry, ...]:
    entries: list[ArchiveEntry] = []
    pending = [root]
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                relative_name = Path(child.path).relative_to(root).as_posix()
                child_stat = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(child_stat.st_mode):
                    kind = "symlink"
                elif bool(getattr(child_stat, "st_file_attributes", 0) & reparse_flag):
                    kind = "reparse"
                elif stat.S_ISDIR(child_stat.st_mode):
                    kind = "directory"
                    pending.append(Path(child.path))
                elif stat.S_ISREG(child_stat.st_mode):
                    kind = "file"
                else:
                    kind = "special"
                entries.append(
                    ArchiveEntry(
                        name=relative_name,
                        kind=kind,
                        uncompressed_bytes=child_stat.st_size if kind == "file" else 0,
                    )
                )
    return tuple(entries)


def _validate_extracted_inventory(
    expected: ArchiveInventory,
    actual: ArchiveInventory,
) -> None:
    expected_entries = _expanded_inventory_contract(expected)
    actual_entries = {
        _archive_destination_key(entry.name): (entry.kind, entry.uncompressed_bytes)
        for entry in actual.entries
    }
    if actual_entries != expected_entries:
        raise ArtifactError(
            "archive_postcheck_failed",
            "Extracted files do not match the preflight archive inventory.",
        )


def _validate_post_extraction(
    expected: ArchiveInventory,
    staging: Path,
    *,
    expected_root: str,
) -> ArchiveInventory:
    try:
        actual = validate_archive_entries(_filesystem_archive_entries(staging))
        validate_portable_archive_inventory(actual, expected_root=expected_root)
        _validate_extracted_inventory(expected, actual)
    except ArtifactError as error:
        if error.code == "archive_postcheck_failed":
            raise
        raise ArtifactError(
            "archive_postcheck_failed",
            "Extracted filesystem objects violate the portable archive contract.",
            {"cause": error.code},
        ) from error
    return actual


def _expanded_inventory_contract(
    inventory: ArchiveInventory,
) -> dict[str, tuple[str, int]]:
    contract: dict[str, tuple[str, int]] = {}
    for entry in inventory.entries:
        destination = _archive_destination_key(entry.name)
        parts = destination.split("/")
        for length in range(1, len(parts)):
            contract.setdefault("/".join(parts[:length]), ("directory", 0))
        contract[destination] = (entry.kind, entry.uncompressed_bytes)
    return contract


def _is_regular_non_reparse_file(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISREG(path_stat.st_mode) and not bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _is_directory_non_reparse(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISDIR(path_stat.st_mode) and not bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _absolute_without_resolving_links(path: Path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _archive_destination_key(name: object) -> str:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 32_767
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or "\x00" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise _unsafe_archive("invalid_path", name if isinstance(name, str) else None)
    path = PurePosixPath(name)
    parts = name.split("/")
    if (
        path.is_absolute()
        or str(path) != name
        or len(parts) > 256
        or any(
            not part
            or part in {".", ".."}
            or len(part) > 255
            or part.endswith((".", " "))
            for part in parts
        )
    ):
        raise _unsafe_archive("invalid_path", name)
    for part in parts:
        device_candidate = part.split(".", 1)[0].upper()
        if device_candidate in _WINDOWS_DEVICE_NAMES:
            raise _unsafe_archive("windows_device_name", name)
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in parts)


def _unsafe_archive(reason: str, entry: str | None = None) -> ArtifactError:
    details: dict[str, object] = {"reason": reason}
    if entry is not None:
        details["entry"] = entry
    return ArtifactError(
        "unsafe_archive",
        "Archive inventory violates the safe extraction boundary.",
        details,
    )


class _PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, source_host: str, allow_loopback_http: bool) -> None:
        super().__init__()
        self.source_host = source_host
        self.allow_loopback_http = allow_loopback_http

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_transport_url(
            newurl,
            self.source_host,
            allow_loopback_http=self.allow_loopback_http,
            redirect=True,
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_cache_path(artifact: BootstrapArtifact, cache_dir: Path) -> Path:
    suffix = ".7z" if artifact.archive_format == "7z" else ".safetensors"
    return Path(cache_dir).expanduser().resolve() / f"{artifact.sha256}{suffix}"


def download_part_path(artifact: BootstrapArtifact, cache_dir: Path) -> Path:
    destination = download_cache_path(artifact, cache_dir)
    return destination.with_suffix(destination.suffix + ".part")


def download_verified(
    artifact: BootstrapArtifact,
    cache_dir: Path,
    *,
    opener: Callable[..., object] | None = None,
    chunk_bytes: int = 1024 * 1024,
    timeout_seconds: float = 30.0,
    allow_loopback_http: bool = False,
) -> Path:
    _validate_download_arguments(
        artifact,
        chunk_bytes=chunk_bytes,
        timeout_seconds=timeout_seconds,
        allow_loopback_http=allow_loopback_http,
    )
    _validate_transport_url(
        artifact.source_url,
        artifact.source_host,
        allow_loopback_http=allow_loopback_http,
        redirect=False,
    )

    destination = download_cache_path(artifact, cache_dir)
    part_path = download_part_path(artifact, cache_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _is_exact_regular_file(destination, artifact.byte_size, artifact.sha256):
            return destination
        raise ArtifactError(
            "cached_artifact_mismatch",
            "Existing cache artifact does not match the frozen size and SHA-256.",
            {"path": str(destination)},
        )

    resume_offset = _resume_offset(part_path, artifact.byte_size)
    if resume_offset == artifact.byte_size:
        if _sha256_file(part_path) != artifact.sha256:
            part_path.unlink()
            raise ArtifactError(
                "download_hash_mismatch",
                "Completed partial download does not match the frozen SHA-256.",
            )
        os.replace(part_path, destination)
        return destination

    request = urllib.request.Request(artifact.source_url, method="GET")
    if resume_offset:
        request.add_header("Range", f"bytes={resume_offset}-")
    client = opener or urllib.request.build_opener(
        _PolicyRedirectHandler(artifact.source_host, allow_loopback_http)
    ).open

    try:
        response = client(request, timeout=timeout_seconds)
        with response:
            final_url = response.geturl()
            _validate_transport_url(
                final_url,
                artifact.source_host,
                allow_loopback_http=allow_loopback_http,
                redirect=final_url != artifact.source_url,
            )
            status = getattr(response, "status", response.getcode())
            write_mode, initial_bytes, expected_response_bytes = _response_contract(
                response,
                status=status,
                resume_offset=resume_offset,
                artifact_size=artifact.byte_size,
            )
            _stream_response(
                response,
                part_path,
                write_mode=write_mode,
                initial_bytes=initial_bytes,
                expected_response_bytes=expected_response_bytes,
                artifact_size=artifact.byte_size,
                chunk_bytes=chunk_bytes,
            )
    except ArtifactError:
        raise
    except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as error:
        raise ArtifactError(
            "download_failed",
            "Artifact download failed; verified cache was not promoted.",
            {"error_type": type(error).__name__, "partial_path": str(part_path)},
        ) from error

    if part_path.stat().st_size != artifact.byte_size:
        raise ArtifactError(
            "download_interrupted",
            "Artifact transfer ended early; partial state is retained for resume.",
            {"partial_path": str(part_path), "bytes": part_path.stat().st_size},
        )
    if _sha256_file(part_path) != artifact.sha256:
        part_path.unlink()
        raise ArtifactError(
            "download_hash_mismatch",
            "Downloaded bytes do not match the frozen SHA-256.",
        )
    os.replace(part_path, destination)
    return destination


def _response_contract(
    response: object,
    *,
    status: int,
    resume_offset: int,
    artifact_size: int,
) -> tuple[str, int, int]:
    headers = response.headers
    try:
        content_length = int(headers.get("Content-Length", ""))
    except (TypeError, ValueError) as error:
        raise ArtifactError(
            "download_length_mismatch",
            "Download response requires an exact Content-Length.",
        ) from error

    if resume_offset and status == 206:
        expected_response_bytes = artifact_size - resume_offset
        expected_range = f"bytes {resume_offset}-{artifact_size - 1}/{artifact_size}"
        if headers.get("Content-Range") != expected_range:
            raise ArtifactError(
                "download_range_mismatch",
                "Resume response does not match the requested frozen byte range.",
            )
        write_mode = "ab"
        initial_bytes = resume_offset
    elif status == 200:
        expected_response_bytes = artifact_size
        write_mode = "wb"
        initial_bytes = 0
    elif not resume_offset and status == 206:
        expected_response_bytes = artifact_size
        expected_range = f"bytes 0-{artifact_size - 1}/{artifact_size}"
        if headers.get("Content-Range") != expected_range:
            raise ArtifactError(
                "download_range_mismatch",
                "Initial partial response does not cover the complete artifact.",
            )
        write_mode = "wb"
        initial_bytes = 0
    else:
        raise ArtifactError(
            "download_status_rejected",
            "Download response status is not valid for the requested transfer.",
            {"status": status},
        )
    if content_length != expected_response_bytes:
        raise ArtifactError(
            "download_length_mismatch",
            "Download Content-Length does not match the frozen byte contract.",
            {"expected": expected_response_bytes, "actual": content_length},
        )
    return write_mode, initial_bytes, expected_response_bytes


def _stream_response(
    response: object,
    part_path: Path,
    *,
    write_mode: str,
    initial_bytes: int,
    expected_response_bytes: int,
    artifact_size: int,
    chunk_bytes: int,
) -> None:
    response_bytes = 0
    with part_path.open(write_mode) as stream:
        while True:
            block = response.read(chunk_bytes)
            if not block:
                break
            response_bytes += len(block)
            total_bytes = initial_bytes + response_bytes
            if response_bytes > expected_response_bytes or total_bytes > artifact_size:
                stream.close()
                part_path.unlink(missing_ok=True)
                raise ArtifactError(
                    "download_oversize",
                    "Download exceeded the frozen artifact byte ceiling.",
                )
            stream.write(block)
    if response_bytes != expected_response_bytes:
        raise ArtifactError(
            "download_interrupted",
            "Artifact transfer ended early; partial state is retained for resume.",
            {"partial_path": str(part_path), "bytes": initial_bytes + response_bytes},
        )


def _resume_offset(path: Path, artifact_size: int) -> int:
    if not path.exists():
        return 0
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise ArtifactError("invalid_download_part", "Partial download cannot be inspected.") from error
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)
        or not 0 <= path_stat.st_size <= artifact_size
    ):
        raise ArtifactError(
            "invalid_download_part",
            "Partial download must be a bounded regular file.",
            {"path": str(path)},
        )
    return path_stat.st_size


def _is_exact_regular_file(path: Path, byte_size: int, sha256: str) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return (
        stat.S_ISREG(path_stat.st_mode)
        and not bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)
        and path_stat.st_size == byte_size
        and _sha256_file(path) == sha256
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_download_arguments(
    artifact: BootstrapArtifact,
    *,
    chunk_bytes: int,
    timeout_seconds: float,
    allow_loopback_http: bool,
) -> None:
    if (
        artifact.kind not in {"comfyui", "model"}
        or not isinstance(artifact.source_url, str)
        or not isinstance(artifact.source_host, str)
        or not artifact.source_host
        or type(artifact.byte_size) is not int
        or not 0 < artifact.byte_size <= MAX_ARTIFACT_BYTES
        or not isinstance(artifact.sha256, str)
        or _SHA256.fullmatch(artifact.sha256) is None
        or (artifact.kind == "comfyui" and artifact.archive_format != "7z")
        or (artifact.kind == "model" and artifact.archive_format is not None)
    ):
        raise ArtifactError("invalid_download_artifact", "Artifact download contract is invalid.")
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= MAX_DOWNLOAD_CHUNK_BYTES:
        raise ArtifactError("invalid_download_options", "chunk_bytes is outside the supported range.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= MAX_DOWNLOAD_TIMEOUT_SECONDS
        or type(allow_loopback_http) is not bool
    ):
        raise ArtifactError("invalid_download_options", "Download timeout or transport mode is invalid.")


def _validate_transport_url(
    url: str,
    source_host: str,
    *,
    allow_loopback_http: bool,
    redirect: bool,
) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise ArtifactError("insecure_download_source", "Download URL is malformed.") from error
    host = (parsed.hostname or "").lower()
    allowed_hosts = {source_host.lower()}
    if redirect:
        allowed_hosts.update(APPROVED_REDIRECT_HOSTS_BY_SOURCE.get(source_host.lower(), ()))
    loopback_http = (
        allow_loopback_http
        and parsed.scheme == "http"
        and host in _LOOPBACK_HOSTS
        and host == source_host.lower()
    )
    if (
        not host
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not loopback_http)
        or (parsed.scheme != "https" and not loopback_http)
    ):
        code = "download_redirect_not_allowed" if redirect else "insecure_download_source"
        raise ArtifactError(
            code,
            "Download URL or redirect is outside the approved transport policy.",
            {"host": host},
        )
