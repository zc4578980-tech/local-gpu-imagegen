from __future__ import annotations

import hashlib
import os
import re
import socket
import stat
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .bootstrap_catalog import MAX_ARTIFACT_BYTES, BootstrapArtifact
from .errors import ArtifactError


MAX_DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_TIMEOUT_SECONDS = 300.0
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
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


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
