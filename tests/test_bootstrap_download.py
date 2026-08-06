from __future__ import annotations

import hashlib
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import py7zr


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.bootstrap_catalog import BootstrapArtifact  # noqa: E402
from local_gpu_imagegen.bootstrap_download import (  # noqa: E402
    ArchiveEntry,
    ArchiveInventory,
    _BoundedArchiveFile,
    _ControlledWriterFactory,
    _OwnedPath,
    _PolicyRedirectHandler,
    _capture_directory_chain,
    download_part_path,
    download_verified,
    safe_extract_portable,
    validate_archive_entries,
    validate_portable_archive_inventory,
)
from local_gpu_imagegen.errors import ArtifactError  # noqa: E402


def create_directory_alias(alias: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(alias))
    else:
        alias.symlink_to(target, target_is_directory=True)


class DownloadFixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, payload: bytes) -> None:
        super().__init__(("127.0.0.1", 0), DownloadFixtureHandler)
        self.payload = payload
        self.requests: list[dict[str, str | None]] = []


class DownloadFixtureHandler(BaseHTTPRequestHandler):
    server: DownloadFixtureServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        range_header = self.headers.get("Range")
        self.server.requests.append({"path": self.path, "range": range_header})
        payload = self.server.payload

        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/full")
            self.end_headers()
            return
        if self.path == "/redirect-host":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/full")
            self.end_headers()
            return
        if self.path == "/timeout":
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.flush()
            threading.Event().wait(0.5)
            return
        if self.path == "/bad-length":
            self._send(200, payload, declared_length=len(payload) + 1)
            return
        if self.path == "/oversize":
            self._send(200, payload + b"x", declared_length=len(payload) + 1)
            return
        if self.path == "/early-eof":
            self._send(200, payload[: len(payload) // 2], declared_length=len(payload))
            return
        if self.path == "/wrong-hash":
            wrong = bytes(value ^ 0xFF for value in payload)
            self._send(200, wrong)
            return
        if self.path == "/interrupt" and range_header is None:
            self._send(200, payload[: len(payload) // 2], declared_length=len(payload))
            return

        if range_header is not None and self.path != "/ignore-range":
            prefix = "bytes="
            start = int(range_header.removeprefix(prefix).removesuffix("-"))
            body = payload[start:]
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
            self.end_headers()
            self.wfile.write(body)
            return

        self._send(200, payload)

    def _send(self, status: int, body: bytes, *, declared_length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body) if declared_length is None else declared_length))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        if declared_length is not None and declared_length > len(body):
            try:
                self.connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass


class BootstrapDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = bytes(range(256)) * 256
        self.server = DownloadFixtureServer(self.payload)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.cache = Path(self.temporary_directory.name) / "cache"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def artifact(self, path: str, *, digest: str | None = None, size: int | None = None) -> BootstrapArtifact:
        return BootstrapArtifact(
            kind="model",
            artifact_id="fixture-model",
            version="fixture-v1",
            source_url=f"http://127.0.0.1:{self.server.server_port}{path}",
            source_host="127.0.0.1",
            byte_size=len(self.payload) if size is None else size,
            sha256=digest or hashlib.sha256(self.payload).hexdigest(),
            license_id="LicenseRef-Fixture",
            license_url="https://models.example.invalid/LICENSE",
            install_relative_path="ComfyUI/models/checkpoints/fixture.safetensors",
            archive_format=None,
            minimum_vram_gb=1,
        )

    def download(self, artifact: BootstrapArtifact, *, timeout_seconds: float = 1.0) -> Path:
        return download_verified(
            artifact,
            self.cache,
            chunk_bytes=4096,
            timeout_seconds=timeout_seconds,
            allow_loopback_http=True,
        )

    def assert_artifact_error(self, code: str, operation) -> ArtifactError:
        with self.assertRaises(ArtifactError) as raised:
            operation()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_full_transfer_returns_only_exact_verified_cache_file(self) -> None:
        artifact = self.artifact("/full")

        result = self.download(artifact)

        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(result.stat().st_size, artifact.byte_size)
        self.assertFalse(download_part_path(artifact, self.cache).exists())
        self.assertEqual(self.server.requests, [{"path": "/full", "range": None}])

    def test_interrupted_transfer_retains_part_and_resumes_with_range(self) -> None:
        artifact = self.artifact("/interrupt")
        part = download_part_path(artifact, self.cache)

        self.assert_artifact_error("download_interrupted", lambda: self.download(artifact))
        self.assertEqual(part.read_bytes(), self.payload[: len(self.payload) // 2])

        result = self.download(artifact)

        self.assertEqual(result.read_bytes(), self.payload)
        self.assertFalse(part.exists())
        self.assertEqual(self.server.requests[-1]["range"], f"bytes={len(self.payload) // 2}-")

    def test_server_ignoring_range_restarts_from_zero(self) -> None:
        artifact = self.artifact("/ignore-range")
        part = download_part_path(artifact, self.cache)
        part.parent.mkdir(parents=True)
        part.write_bytes(self.payload[:4096])

        result = self.download(artifact)

        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual(self.server.requests[-1]["range"], "bytes=4096-")

    def test_same_host_redirect_is_allowed(self) -> None:
        artifact = self.artifact("/redirect")

        result = self.download(artifact)

        self.assertEqual(result.read_bytes(), self.payload)
        self.assertEqual([item["path"] for item in self.server.requests], ["/redirect", "/full"])

    def test_redirect_host_drift_is_rejected_before_follow(self) -> None:
        artifact = self.artifact("/redirect-host")

        self.assert_artifact_error("download_redirect_not_allowed", lambda: self.download(artifact))

        self.assertEqual([item["path"] for item in self.server.requests], ["/redirect-host"])

    def test_redirect_allowlist_is_bound_to_the_original_provider(self) -> None:
        handler = _PolicyRedirectHandler("github.com", False)
        request = urllib.request.Request(
            "https://github.com/Comfy-Org/ComfyUI/releases/download/v0.30.0/archive.7z"
        )

        self.assert_artifact_error(
            "download_redirect_not_allowed",
            lambda: handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://cdn-lfs.hf.co/unrelated/model.safetensors",
            ),
        )

    def test_plain_http_is_rejected_without_explicit_loopback_test_mode(self) -> None:
        artifact = self.artifact("/full")

        self.assert_artifact_error(
            "insecure_download_source",
            lambda: download_verified(artifact, self.cache),
        )

        self.assertEqual(self.server.requests, [])
    def test_invalid_artifact_types_fail_structurally_before_request(self) -> None:
        artifact = self.artifact("/full")
        invalid_artifacts = (
            replace(artifact, sha256=True),
            replace(artifact, source_host=True),
            replace(artifact, archive_format="zip"),
        )
        for invalid in invalid_artifacts:
            with self.subTest(invalid=invalid):
                self.assert_artifact_error(
                    "invalid_download_artifact",
                    lambda: self.download(invalid),
                )
        self.assertEqual(self.server.requests, [])

    def test_declared_length_mismatch_and_oversize_are_rejected_before_write(self) -> None:
        for route in ("/bad-length", "/oversize"):
            with self.subTest(route=route):
                artifact = self.artifact(route)
                self.assert_artifact_error("download_length_mismatch", lambda: self.download(artifact))
                self.assertFalse(download_part_path(artifact, self.cache).exists())

    def test_stream_exceeding_declared_artifact_size_is_deleted(self) -> None:
        artifact = self.artifact("/full")

        class OversizeResponse:
            status = 200
            headers = {"Content-Length": str(artifact.byte_size)}

            def __init__(self) -> None:
                self.remaining = self_payload + b"x"

            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return artifact.source_url

            def getcode(self) -> int:
                return self.status

            def read(self, _size: int) -> bytes:
                block, self.remaining = self.remaining, b""
                return block

        self_payload = self.payload
        self.assert_artifact_error(
            "download_oversize",
            lambda: download_verified(
                artifact,
                self.cache,
                opener=lambda *_args, **_kwargs: OversizeResponse(),
                allow_loopback_http=True,
            ),
        )
        self.assertFalse(download_part_path(artifact, self.cache).exists())

    def test_early_eof_retains_resumable_part(self) -> None:
        artifact = self.artifact("/early-eof")

        self.assert_artifact_error("download_interrupted", lambda: self.download(artifact))

        self.assertEqual(
            download_part_path(artifact, self.cache).read_bytes(),
            self.payload[: len(self.payload) // 2],
        )

    def test_timeout_is_structured_and_never_promotes_part(self) -> None:
        artifact = self.artifact("/timeout")

        self.assert_artifact_error(
            "download_failed",
            lambda: self.download(artifact, timeout_seconds=0.05),
        )

        self.assertEqual(list(self.cache.glob("*.safetensors")), [])

    def test_wrong_hash_removes_completed_corrupt_part(self) -> None:
        artifact = self.artifact("/wrong-hash")

        self.assert_artifact_error("download_hash_mismatch", lambda: self.download(artifact))

        self.assertFalse(download_part_path(artifact, self.cache).exists())
        self.assertEqual(list(self.cache.glob("*.safetensors")), [])

    def test_exact_existing_cache_file_is_reused_without_request(self) -> None:
        artifact = self.artifact("/full")
        destination = self.cache / f"{artifact.sha256}.safetensors"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(self.payload)

        result = self.download(artifact)

        self.assertEqual(result, destination.resolve())
        self.assertEqual(self.server.requests, [])


class ArchiveBoundaryTests(unittest.TestCase):
    @staticmethod
    def entry(
        name: str,
        *,
        kind: str = "file",
        uncompressed_bytes: int = 1,
    ) -> ArchiveEntry:
        return ArchiveEntry(
            name=name,
            kind=kind,
            uncompressed_bytes=0 if kind == "directory" else uncompressed_bytes,
        )

    def assert_unsafe(self, entries: list[ArchiveEntry], reason: str) -> None:
        with self.assertRaises(ArtifactError) as raised:
            validate_archive_entries(entries)
        self.assertEqual(raised.exception.code, "unsafe_archive")
        self.assertEqual(raised.exception.details.get("reason"), reason)

    def test_valid_inventory_is_normalized_without_writing(self) -> None:
        entries = [
            self.entry("ComfyUI_windows_portable", kind="directory"),
            self.entry("ComfyUI_windows_portable/python_embeded/python.exe", uncompressed_bytes=16),
            self.entry("ComfyUI_windows_portable/ComfyUI/main.py", uncompressed_bytes=8),
        ]

        inventory = validate_archive_entries(entries)

        self.assertEqual(inventory.entry_count, 3)
        self.assertEqual(inventory.file_count, 2)
        self.assertEqual(inventory.directory_count, 1)
        self.assertEqual(inventory.expanded_bytes, 24)
        self.assertEqual(inventory.entries, tuple(entries))

        validated = validate_portable_archive_inventory(
            inventory,
            expected_root="ComfyUI_windows_portable",
        )
        self.assertIs(validated, inventory)

    def test_portable_layout_rejects_missing_wrong_type_or_outside_markers(self) -> None:
        valid = [
            self.entry("ComfyUI_windows_portable", kind="directory"),
            self.entry("ComfyUI_windows_portable/python_embeded/python.exe"),
            self.entry("ComfyUI_windows_portable/ComfyUI/main.py"),
        ]
        cases = (
            valid[:-1],
            valid[:-2] + valid[-1:],
            [valid[0], replace(valid[1], kind="directory", uncompressed_bytes=0), valid[2]],
            valid + [self.entry("outside.txt")],
        )
        for entries in cases:
            with self.subTest(entries=entries):
                inventory = validate_archive_entries(entries)
                with self.assertRaises(ArtifactError) as raised:
                    validate_portable_archive_inventory(
                        inventory,
                        expected_root="ComfyUI_windows_portable",
                    )
                self.assertEqual(raised.exception.code, "invalid_portable_layout")

    def test_rejects_absolute_drive_unc_traversal_and_ambiguous_paths(self) -> None:
        paths = (
            "/absolute/file",
            "C:/drive/file",
            "C:\\drive\\file",
            "//server/share/file",
            "../outside",
            "root/../outside",
            "root/./file",
            "root//file",
            "root\\file",
            "root/file:stream",
            "root/file.",
            "root/file ",
            "",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assert_unsafe([self.entry(path)], "invalid_path")

    def test_rejects_windows_device_names_in_any_segment(self) -> None:
        paths = (
            "CON",
            "root/nul.txt",
            "root/aux/config.json",
            "root/COM1.bin",
            "root/lpt9/file",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assert_unsafe([self.entry(path)], "windows_device_name")

    def test_rejects_links_reparse_and_special_entries(self) -> None:
        for kind in ("symlink", "hardlink", "reparse", "device", "socket", "unknown"):
            with self.subTest(kind=kind):
                self.assert_unsafe([self.entry("root/item", kind=kind)], "unsupported_entry_kind")

    def test_rejects_exact_casefold_and_unicode_destination_collisions(self) -> None:
        collisions = (
            ("root/file.txt", "root/file.txt"),
            ("root/File.txt", "root/file.TXT"),
            ("root/caf\u00e9.txt", "root/cafe\u0301.txt"),
        )
        for first, second in collisions:
            with self.subTest(first=first, second=second):
                self.assert_unsafe(
                    [self.entry(first), self.entry(second)],
                    "destination_collision",
                )

    def test_rejects_file_parent_conflicts(self) -> None:
        self.assert_unsafe(
            [self.entry("root/item"), self.entry("root/item/child.txt")],
            "file_parent_conflict",
        )

    def test_rejects_excessive_entry_count_and_expanded_bytes(self) -> None:
        with self.assertRaises(ArtifactError) as entries_error:
            validate_archive_entries(
                [self.entry("root/a"), self.entry("root/b")],
                max_entries=1,
            )
        self.assertEqual(entries_error.exception.details.get("reason"), "entry_count_limit")

        with self.assertRaises(ArtifactError) as bytes_error:
            validate_archive_entries(
                [
                    self.entry("root/a", uncompressed_bytes=6),
                    self.entry("root/b", uncompressed_bytes=5),
                ],
                max_expanded_bytes=10,
            )
        self.assertEqual(bytes_error.exception.details.get("reason"), "expanded_bytes_limit")

    def test_rejects_empty_or_invalid_entry_metadata(self) -> None:
        self.assert_unsafe([], "empty_archive")
        invalid_entries = (
            self.entry("root/file", uncompressed_bytes=-1),
            self.entry("root/file", uncompressed_bytes=True),
            replace(self.entry("root/directory", kind="directory"), uncompressed_bytes=1),
        )
        for entry in invalid_entries:
            with self.subTest(entry=entry):
                self.assert_unsafe([entry], "invalid_entry_metadata")


class PortableExtractionTests(unittest.TestCase):
    BCJ2_FIXTURE = Path(__file__).parent / "fixtures" / "bootstrap" / "bcj2-portable.7z"

    @staticmethod
    def write_portable_archive(
        root: Path,
        *,
        include_main: bool = True,
        python_is_directory: bool = False,
        python_bytes: bytes = b"python",
    ) -> Path:
        source = root / "source" / "ComfyUI_windows_portable"
        (source / "python_embeded").mkdir(parents=True)
        (source / "ComfyUI").mkdir()
        python_marker = source / "python_embeded" / "python.exe"
        if python_is_directory:
            python_marker.mkdir()
        else:
            python_marker.write_bytes(python_bytes)
        if include_main:
            (source / "ComfyUI" / "main.py").write_bytes(b"main")
        archive_path = root / "portable.7z"
        with py7zr.SevenZipFile(archive_path, "w") as archive:
            archive.writeall(source, arcname="ComfyUI_windows_portable")
        return archive_path

    def test_verified_archive_snapshot_uses_the_selected_install_volume(self) -> None:
        import local_gpu_imagegen._filesystem_capability as filesystem_capability

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root / "archive")
            selected_volume = root / "selected-volume"
            selected_volume.mkdir()
            install_root = selected_volume / "install"
            original_temporary_file = tempfile.TemporaryFile
            snapshot_directories: list[Path | None] = []

            def capture_snapshot_directory(*args, **kwargs):
                directory = kwargs.get("dir")
                snapshot_directories.append(
                    None if directory is None else Path(directory).resolve()
                )
                return original_temporary_file(*args, **kwargs)

            with mock.patch.object(
                filesystem_capability.tempfile,
                "TemporaryFile",
                side_effect=capture_snapshot_directory,
            ):
                safe_extract_portable(
                    archive_path,
                    install_root,
                    expected_root="ComfyUI_windows_portable",
                    plan_id="7" * 24,
                )

            self.assertEqual(snapshot_directories, [selected_volume.resolve()])

    @unittest.skipUnless(os.name == "nt", "Windows junction swap-back semantics")
    def test_snapshot_ancestor_swap_back_never_receives_archive_bytes(self) -> None:
        import local_gpu_imagegen._filesystem_capability as filesystem_capability

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root / "archive")
            selected_volume = root / "selected-volume"
            selected_volume.mkdir()
            install_root = selected_volume / "install"
            displaced = root / "displaced-volume"
            external = root / "external-volume"
            external.mkdir()
            original_temporary_file = tempfile.TemporaryFile
            external_write_bytes = 0
            swapped = False

            class RecordingTemporaryFile:
                def __init__(self, stream) -> None:
                    self.stream = stream

                def __getattr__(self, name):
                    return getattr(self.stream, name)

                def write(self, value):
                    nonlocal external_write_bytes
                    external_write_bytes += len(value)
                    return self.stream.write(value)

            def swap_back_after_temporary_creation(*args, **kwargs):
                nonlocal swapped
                if swapped:
                    return original_temporary_file(*args, **kwargs)
                selected_volume.replace(displaced)
                create_directory_alias(selected_volume, external)
                try:
                    stream = original_temporary_file(*args, **kwargs)
                finally:
                    os.rmdir(selected_volume)
                    displaced.replace(selected_volume)
                swapped = True
                return RecordingTemporaryFile(stream)

            with mock.patch.object(
                filesystem_capability.tempfile,
                "TemporaryFile",
                side_effect=swap_back_after_temporary_creation,
            ), self.assertRaises(ArtifactError):
                safe_extract_portable(
                    archive_path,
                    install_root,
                    expected_root="ComfyUI_windows_portable",
                    plan_id="9" * 24,
                )

            self.assertTrue(swapped)
            self.assertEqual(external_write_bytes, 0)

    def test_archive_snapshot_without_expected_size_is_bounded(self) -> None:
        import local_gpu_imagegen.bootstrap_download as bootstrap_download

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = root / "oversize.7z"
            archive_path.write_bytes(b"x" * 9)

            with mock.patch.object(
                bootstrap_download,
                "MAX_ARTIFACT_BYTES",
                8,
            ), self.assertRaises(ArtifactError) as raised:
                safe_extract_portable(
                    archive_path,
                    root / "install",
                    expected_root="ComfyUI_windows_portable",
                    plan_id="8" * 24,
                )

            self.assertEqual(raised.exception.code, "invalid_archive_path")
            self.assertEqual(
                list((root / "install").glob(".local-gpu-imagegen-*.staging")),
                [],
            )

    def test_extraction_uses_the_exact_verified_archive_handle_after_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = self.write_portable_archive(root / "approved", python_bytes=b"approved")
            replacement = self.write_portable_archive(root / "replacement", python_bytes=b"unapproved")
            approved_bytes = archive_path.read_bytes()
            approved_sha256 = hashlib.sha256(approved_bytes).hexdigest()
            displaced = root / "approved-original.7z"
            original_seven_zip = py7zr.SevenZipFile

            def replace_path_before_reader(file, *args, **kwargs):
                if (args and args[0] == "r") or kwargs.get("mode") == "r":
                    try:
                        archive_path.replace(displaced)
                        replacement.replace(archive_path)
                    except PermissionError:
                        archive_path.write_bytes(replacement.read_bytes())
                return original_seven_zip(file, *args, **kwargs)

            with mock.patch.object(py7zr, "SevenZipFile", side_effect=replace_path_before_reader):
                destination = safe_extract_portable(
                    archive_path,
                    root / "install",
                    expected_root="ComfyUI_windows_portable",
                    plan_id="3" * 24,
                    expected_byte_size=len(approved_bytes),
                    expected_sha256=approved_sha256,
                )

            self.assertEqual(
                (destination / "python_embeded" / "python.exe").read_bytes(),
                b"approved",
            )

    def test_safe_archive_is_staged_validated_and_atomically_placed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = self.write_portable_archive(root)
            destination = safe_extract_portable(
                archive_path,
                root / "install",
                expected_root="ComfyUI_windows_portable",
                plan_id="a" * 24,
            )

            self.assertEqual(
                destination.resolve(),
                (root / "install" / "ComfyUI_windows_portable").resolve(),
            )
            self.assertEqual((destination / "python_embeded" / "python.exe").read_bytes(), b"python")
            self.assertEqual((destination / "ComfyUI" / "main.py").read_bytes(), b"main")
            self.assertEqual(
                list((root / "install").glob(".local-gpu-imagegen-*.staging")),
                [],
            )

    @unittest.skipUnless(os.name == "nt", "Windows bsdtar BCJ2 fallback")
    def test_official_bcj2_method_is_extracted_through_the_safe_public_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = safe_extract_portable(
                self.BCJ2_FIXTURE,
                root / "install",
                expected_root="ComfyUI_windows_portable",
                plan_id="e" * 24,
            )

            self.assertEqual(
                (destination / "python_embeded" / "python.exe").read_bytes(),
                b'"""Deterministic planning primitives for local visual-asset runs."""\r\n\r\n'
                b'__version__ = "0.8.3"\n',
            )
            self.assertTrue((destination / "ComfyUI" / "main.py").is_file())
            self.assertEqual(
                list((root / "install").glob(".local-gpu-imagegen-*.staging")),
                [],
            )

    @unittest.skipUnless(os.name == "nt", "Windows bsdtar BCJ2 fallback")
    def test_bcj2_stream_closes_each_member_before_opening_the_next_member(self) -> None:
        original_create = _ControlledWriterFactory.create
        original_close = _BoundedArchiveFile.close
        events: list[str] = []

        def tracked_create(
            factory: _ControlledWriterFactory,
            filename: str,
        ) -> _BoundedArchiveFile:
            writer = original_create(factory, filename)
            events.append("open")
            return writer

        def tracked_close(writer: _BoundedArchiveFile) -> None:
            if not writer._closed:
                events.append("close")
            original_close(writer)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with (
                mock.patch.object(
                    _ControlledWriterFactory,
                    "create",
                    autospec=True,
                    side_effect=tracked_create,
                ),
                mock.patch.object(
                    _BoundedArchiveFile,
                    "close",
                    autospec=True,
                    side_effect=tracked_close,
                ),
            ):
                safe_extract_portable(
                    self.BCJ2_FIXTURE,
                    root / "install",
                    expected_root="ComfyUI_windows_portable",
                    plan_id="f" * 24,
                )

        open_members = 0
        peak_open_members = 0
        for event in events:
            open_members += 1 if event == "open" else -1
            peak_open_members = max(peak_open_members, open_members)
        self.assertEqual(open_members, 0)
        self.assertEqual(peak_open_members, 1)

    def test_portable_extraction_never_uses_path_based_extractall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = self.write_portable_archive(root)

            with mock.patch.object(
                py7zr.SevenZipFile,
                "extractall",
                autospec=True,
                side_effect=AssertionError("path-based extraction is forbidden"),
            ):
                destination = safe_extract_portable(
                    archive_path,
                    root / "install",
                    expected_root="ComfyUI_windows_portable",
                    plan_id="5" * 24,
                )

            self.assertTrue((destination / "ComfyUI" / "main.py").is_file())

    def test_staging_replacement_after_creation_fails_before_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root / "archive")
            install_root = root / "install"
            plan_id = "6" * 24
            staging = install_root / f".local-gpu-imagegen-{plan_id}.staging"
            displaced = root / "displaced-staging"
            external = root / "external-staging"
            external.mkdir()
            original_mkdir = Path.mkdir
            alias_error: OSError | None = None

            def replace_staging_after_mkdir(path: Path, *args, **kwargs) -> None:
                nonlocal alias_error
                original_mkdir(path, *args, **kwargs)
                if path == staging:
                    path.replace(displaced)
                    try:
                        create_directory_alias(path, external)
                    except OSError as error:
                        alias_error = error

            with mock.patch.object(Path, "mkdir", new=replace_staging_after_mkdir):
                with self.assertRaises(ArtifactError):
                    safe_extract_portable(
                        archive_path,
                        install_root,
                        expected_root="ComfyUI_windows_portable",
                        plan_id=plan_id,
                    )

            if alias_error is not None:
                self.skipTest(f"directory alias creation unavailable: {type(alias_error).__name__}")
            self.assertEqual(list(external.rglob("*")), [])
            self.assertFalse((install_root / "ComfyUI_windows_portable").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction swap-back semantics")
    def test_portable_writer_swap_back_never_writes_nonempty_external_file(self) -> None:
        import local_gpu_imagegen.bootstrap_download as bootstrap_download

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root / "archive")
            install_root = root / "install"
            plan_id = "d" * 24
            staging = install_root / f".local-gpu-imagegen-{plan_id}.staging"
            parent = staging / "python_embeded"
            destination = parent / "python.exe"
            displaced = root / "displaced-python-parent"
            external = root / "external-python-parent"
            external.mkdir()
            original_open = os.open
            original_path_open = Path.open
            original_lstat = Path.lstat
            swapped = False
            restored = False

            def swap_parent_for(candidate: Path) -> None:
                nonlocal swapped
                if candidate == destination and not swapped:
                    parent.replace(displaced)
                    create_directory_alias(parent, external)
                    swapped = True

            def redirect_open(path, flags, *args, **kwargs):
                swap_parent_for(Path(path))
                return original_open(path, flags, *args, **kwargs)

            def redirect_path_open(path: Path, *args, **kwargs):
                swap_parent_for(path)
                return original_path_open(path, *args, **kwargs)

            def restore_after_path_stat(path: Path, *args, **kwargs):
                nonlocal restored
                current = original_lstat(path, *args, **kwargs)
                if path == destination and swapped and not restored:
                    os.rmdir(parent)
                    displaced.replace(parent)
                    restored = True
                return current

            with mock.patch.object(
                bootstrap_download.os,
                "open",
                side_effect=redirect_open,
            ), mock.patch.object(
                Path,
                "open",
                new=redirect_path_open,
            ), mock.patch.object(Path, "lstat", new=restore_after_path_stat):
                with self.assertRaises(ArtifactError):
                    safe_extract_portable(
                        archive_path,
                        install_root,
                        expected_root="ComfyUI_windows_portable",
                        plan_id=plan_id,
                    )

            self.assertTrue(swapped)
            self.assertTrue(restored)
            external_file = external / "python.exe"
            self.assertTrue(not external_file.exists() or external_file.read_bytes() == b"")

    def test_controlled_writer_uses_constant_time_parent_identity_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            staging = root / ".local-gpu-imagegen-staging"
            parent = staging / "python_embeded"
            parent.mkdir(parents=True)
            staging_identity = staging.lstat()
            parent_identity = parent.lstat()
            inventory = ArchiveInventory(
                entries=(
                    ArchiveEntry(
                        "ComfyUI_windows_portable/python_embeded/python.exe",
                        "file",
                        1,
                    ),
                ),
                entry_count=1,
                file_count=1,
                directory_count=0,
                expanded_bytes=1,
            )

            class NonIterableOwnedPaths(list):
                def __iter__(self):
                    raise AssertionError("writer parent lookup scanned ordered cleanup records")

            owned_paths = NonIterableOwnedPaths(
                [_OwnedPath(parent, parent_identity, "directory")]
            )
            writer_factory = _ControlledWriterFactory(
                staging,
                staging_identity,
                root,
                _capture_directory_chain(root),
                inventory,
                "ComfyUI_windows_portable",
                owned_paths,
                {
                    staging: staging_identity,
                    parent: parent_identity,
                },
            )

            writer = writer_factory.create(
                str(staging / "ComfyUI_windows_portable" / "python_embeded" / "python.exe")
            )
            writer.write(b"x")
            writer_factory.finish()
            self.assertEqual((parent / "python.exe").read_bytes(), b"x")

    def test_missing_or_wrong_type_portable_markers_fail_before_promotion(self) -> None:
        cases = (
            {"include_main": False},
            {"python_is_directory": True},
        )
        for index, options in enumerate(cases):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                archive_path = self.write_portable_archive(root, **options)

                with self.assertRaises(ArtifactError) as raised:
                    safe_extract_portable(
                        archive_path,
                        root / "install",
                        expected_root="ComfyUI_windows_portable",
                        plan_id=f"{index + 1:024x}",
                    )

                self.assertEqual(raised.exception.code, "invalid_portable_layout")
                self.assertFalse((root / "install" / "ComfyUI_windows_portable").exists())
                retained_staging = list(
                    (root / "install").glob(".local-gpu-imagegen-*.staging")
                )
                self.assertEqual(len(retained_staging), 0 if os.name == "nt" else 1)

    def test_extractor_failure_preserves_other_plan_and_uses_platform_cleanup_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root)
            install_root = root / "install"
            other_staging = install_root / f".local-gpu-imagegen-{'c' * 24}.staging"
            other_staging.mkdir(parents=True)
            sentinel = other_staging / "owner.txt"
            sentinel.write_text("keep", encoding="utf-8")

            def fail_after_partial_write(_archive, path, **kwargs):
                factory = kwargs["factory"]
                writer = factory.create(
                    (Path(path) / "ComfyUI_windows_portable" / "python_embeded" / "python.exe").as_posix()
                )
                writer.write(b"p")
                raise RuntimeError("fixture extraction failure")

            with mock.patch.object(
                py7zr.SevenZipFile,
                "extract",
                autospec=True,
                side_effect=fail_after_partial_write,
            ), self.assertRaises(ArtifactError) as raised:
                safe_extract_portable(
                    archive_path,
                    install_root,
                    expected_root="ComfyUI_windows_portable",
                    plan_id="d" * 24,
            )

            self.assertEqual(raised.exception.code, "archive_extract_failed")
            current_staging = install_root / f".local-gpu-imagegen-{'d' * 24}.staging"
            self.assertEqual(current_staging.exists(), os.name != "nt")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertFalse((install_root / "ComfyUI_windows_portable").exists())

    def test_post_extraction_inventory_drift_retains_unowned_residue(self) -> None:
        original_extract = py7zr.SevenZipFile.extract
        for index, mutation in enumerate(("unexpected_file", "type_drift")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                archive_path = self.write_portable_archive(root)
                install_root = root / "install"

                def extract_and_mutate(archive, path, **kwargs):
                    original_extract(archive, path, **kwargs)
                    portable = Path(path)
                    if mutation == "unexpected_file":
                        (portable / "unexpected.bin").write_bytes(b"unexpected")
                    else:
                        marker = portable / "python_embeded" / "python.exe"
                        marker.unlink()
                        marker.mkdir()

                with mock.patch.object(
                    py7zr.SevenZipFile,
                    "extract",
                    autospec=True,
                    side_effect=extract_and_mutate,
                ), self.assertRaises(ArtifactError) as raised:
                    safe_extract_portable(
                        archive_path,
                        install_root,
                        expected_root="ComfyUI_windows_portable",
                        plan_id=f"{index + 14:024x}",
                    )

                self.assertEqual(raised.exception.code, "archive_postcheck_failed")
                self.assertFalse((install_root / "ComfyUI_windows_portable").exists())
                retained_staging = (
                    install_root / f".local-gpu-imagegen-{index + 14:024x}.staging"
                )
                self.assertTrue(retained_staging.is_dir())
                if mutation == "unexpected_file":
                    self.assertEqual(
                        (retained_staging / "unexpected.bin").read_bytes(),
                        b"unexpected",
                    )
                else:
                    self.assertTrue(
                        (retained_staging / "python_embeded" / "python.exe").is_dir()
                    )
                quarantined = [
                    path
                    for path in install_root.iterdir()
                    if path.name.endswith(".cleanup")
                ]
                self.assertEqual(quarantined, [])

    def test_exact_py7zr_version_is_required_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = self.write_portable_archive(root)
            install_root = root / "install"

            with mock.patch(
                "local_gpu_imagegen.bootstrap_download.importlib.metadata.version",
                return_value="1.1.4",
            ), self.assertRaises(ArtifactError) as raised:
                safe_extract_portable(
                    archive_path,
                    install_root,
                    expected_root="ComfyUI_windows_portable",
                    plan_id="f" * 24,
                )

            self.assertEqual(raised.exception.code, "extractor_dependency_mismatch")
            self.assertFalse((install_root / "ComfyUI_windows_portable").exists())
            self.assertEqual(
                list(install_root.glob(".local-gpu-imagegen-*.staging")),
                [],
            )

    def test_successful_promotion_is_not_reported_failed_when_staging_cleanup_races(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root)
            install_root = root / "install"
            plan_id = "1" * 24
            staging = install_root / f".local-gpu-imagegen-{plan_id}.staging"
            original_rmdir = Path.rmdir

            def fail_once_for_staging(path: Path) -> None:
                if path == staging:
                    raise OSError("fixture cleanup race")
                original_rmdir(path)

            with mock.patch.object(Path, "rmdir", new=fail_once_for_staging):
                destination = safe_extract_portable(
                    archive_path,
                    install_root,
                    expected_root="ComfyUI_windows_portable",
                    plan_id=plan_id,
                )

            self.assertEqual(destination, install_root / "ComfyUI_windows_portable")
            self.assertTrue((destination / "ComfyUI" / "main.py").is_file())
            self.assertFalse(staging.exists())

    @unittest.skipUnless(os.name == "nt", "Windows handle-relative promotion semantics")
    def test_promotion_time_swap_back_returns_portable_to_captured_root(self) -> None:
        import local_gpu_imagegen._filesystem_capability as filesystem_capability
        import local_gpu_imagegen.bootstrap_download as bootstrap_download

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root / "archive")
            install_root = root / "install"
            external = root / "external"
            external.mkdir()
            displaced_root = root / "captured-install"
            plan_id = "7" * 24
            staging = install_root / f".local-gpu-imagegen-{plan_id}.staging"
            destination = install_root / "ComfyUI_windows_portable"
            external_staging = external / staging.name
            original_descriptor_promote = filesystem_capability._promote_descriptor_no_replace
            original_promote = bootstrap_download.promote_owned_path_no_replace
            swapped = False
            restored = False

            def swap_during_descriptor_promotion(*args, **kwargs) -> None:
                nonlocal swapped
                staging.replace(external_staging)
                install_root.replace(displaced_root)
                create_directory_alias(install_root, external)
                swapped = True
                original_descriptor_promote(*args, **kwargs)

            def restore_after_capability_closes(*args, **kwargs):
                nonlocal restored
                try:
                    return original_promote(*args, **kwargs)
                finally:
                    if swapped:
                        os.rmdir(install_root)
                        displaced_root.replace(install_root)
                        restored = True

            with mock.patch.object(
                filesystem_capability,
                "_promote_descriptor_no_replace",
                side_effect=swap_during_descriptor_promotion,
            ), mock.patch.object(
                bootstrap_download,
                "promote_owned_path_no_replace",
                side_effect=restore_after_capability_closes,
            ):
                result = safe_extract_portable(
                    archive_path,
                    install_root,
                    expected_root="ComfyUI_windows_portable",
                    plan_id=plan_id,
                )

            self.assertTrue(swapped)
            self.assertTrue(restored)
            self.assertEqual(result, destination)
            self.assertTrue((destination / "ComfyUI" / "main.py").is_file())
            self.assertEqual(list(external.rglob("*")), [])

    def test_post_promotion_parent_swap_never_cleans_external_paths(self) -> None:
        import local_gpu_imagegen.bootstrap_download as bootstrap_download

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root / "archive")
            planned_parent = root / "planned-parent"
            install_root = planned_parent / "install"
            install_root.mkdir(parents=True)
            displaced_parent = root / "displaced-parent"
            external_parent = root / "external-parent"
            (external_parent / "install").mkdir(parents=True)
            plan_id = "4" * 24
            destination = install_root / "ComfyUI_windows_portable"
            staging = install_root / f".local-gpu-imagegen-{plan_id}.staging"
            external_destination_sentinel = (
                external_parent / "install" / "ComfyUI_windows_portable" / "owner.txt"
            )
            external_staging_sentinel = (
                external_parent
                / "install"
                / f".local-gpu-imagegen-{plan_id}.staging"
                / "owner.txt"
            )
            original_promote = bootstrap_download.promote_owned_path_no_replace
            alias_error: OSError | None = None

            def promote_then_swap_parent(*args, **kwargs) -> None:
                nonlocal alias_error
                original_promote(*args, **kwargs)
                planned_parent.replace(displaced_parent)
                try:
                    create_directory_alias(planned_parent, external_parent)
                except OSError as error:
                    alias_error = error
                else:
                    external_destination_sentinel.parent.mkdir()
                    external_destination_sentinel.write_text("keep", encoding="utf-8")
                    external_staging_sentinel.parent.mkdir()
                    external_staging_sentinel.write_text("keep", encoding="utf-8")

            with mock.patch.object(
                bootstrap_download,
                "promote_owned_path_no_replace",
                side_effect=promote_then_swap_parent,
            ), self.assertRaises(ArtifactError) as raised:
                safe_extract_portable(
                    archive_path,
                    install_root,
                    expected_root="ComfyUI_windows_portable",
                    plan_id=plan_id,
                )

            if alias_error is not None:
                self.skipTest(f"directory alias creation unavailable: {type(alias_error).__name__}")
            self.assertEqual(raised.exception.code, "archive_extract_failed")
            self.assertEqual(external_destination_sentinel.read_text(encoding="utf-8"), "keep")
            self.assertEqual(external_staging_sentinel.read_text(encoding="utf-8"), "keep")
            self.assertTrue(
                (
                    displaced_parent
                    / "install"
                    / "ComfyUI_windows_portable"
                    / "ComfyUI"
                    / "main.py"
                ).is_file()
            )
            self.assertFalse((displaced_parent / "install" / staging.name).exists())

    def test_archive_symlink_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            archive_path = self.write_portable_archive(root)
            archive_link = root / "portable-link.7z"
            try:
                archive_link.symlink_to(archive_path)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {type(error).__name__}")

            with self.assertRaises(ArtifactError) as raised:
                safe_extract_portable(
                    archive_link,
                    root / "install",
                    expected_root="ComfyUI_windows_portable",
                    plan_id="2" * 24,
                )

            self.assertEqual(raised.exception.code, "invalid_archive_path")
            self.assertFalse((root / "install" / "ComfyUI_windows_portable").exists())

    def test_existing_destination_is_preserved_without_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = self.write_portable_archive(root)
            destination = root / "install" / "ComfyUI_windows_portable"
            destination.mkdir(parents=True)
            sentinel = destination / "owner.txt"
            sentinel.write_text("keep", encoding="utf-8")

            with self.assertRaises(ArtifactError) as raised:
                safe_extract_portable(
                    archive_path,
                    root / "install",
                    expected_root="ComfyUI_windows_portable",
                    plan_id="b" * 24,
                )

            self.assertEqual(raised.exception.code, "portable_destination_conflict")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertEqual(
                list((root / "install").glob(".local-gpu-imagegen-*.staging")),
                [],
            )


if __name__ == "__main__":
    unittest.main()
