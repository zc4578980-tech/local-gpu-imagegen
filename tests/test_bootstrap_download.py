from __future__ import annotations

import hashlib
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.bootstrap_catalog import BootstrapArtifact  # noqa: E402
from local_gpu_imagegen.bootstrap_download import (  # noqa: E402
    _PolicyRedirectHandler,
    download_part_path,
    download_verified,
)
from local_gpu_imagegen.errors import ArtifactError  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
