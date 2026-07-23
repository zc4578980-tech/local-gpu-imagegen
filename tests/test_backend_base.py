from __future__ import annotations

import sys
import unittest


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.backends.base import (  # noqa: E402
    BackendRegistry,
    BoundedJsonClient,
    EndpointPolicy,
)
from local_gpu_imagegen.errors import ArtifactError, StateError, ValidationError  # noqa: E402
from tests.fake_backend_server import FakeBackendServer, FakeResponse  # noqa: E402


class FakeAdapter:
    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id
        self.endpoint_identity = f"endpoint:{backend_id}"

    def probe(self) -> dict[str, object]:
        return {"backend": self.backend_id, "ready": True}

    def discover(self) -> list[dict[str, object]]:
        return [{"backend": self.backend_id, "backend_model_id": "model"}]

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        return {"backend": self.backend_id, "request": request}

    def layout_capability(self, mode: str) -> dict[str, object]:
        return {
            "mode": mode,
            "available": True,
            "endpoint_identity": self.endpoint_identity,
            "reason": None,
        }

    def cancel_or_query(
        self,
        job_id: str,
        *,
        cancel: bool = False,
    ) -> dict[str, object]:
        return {"job_id": job_id, "cancel": cancel}


class EndpointPolicyTests(unittest.TestCase):
    def test_loopback_is_local_and_canonical(self) -> None:
        first = EndpointPolicy.resolve("http://127.0.0.1:7860/")
        second = EndpointPolicy.resolve("http://127.0.0.1:7860")

        self.assertEqual(first, second)
        self.assertEqual(first["base_url"], "http://127.0.0.1:7860")
        self.assertEqual(first["class"], "loopback")
        self.assertRegex(first["endpoint_identity"], r"^endpoint:[0-9a-f]{64}$")
        self.assertEqual(
            EndpointPolicy.resolve("http://localhost:8188")["class"],
            "loopback",
        )

    def test_public_endpoint_is_rejected(self) -> None:
        for url in ("http://8.8.8.8:7860", "http://203.0.113.10:8188"):
            with self.subTest(url=url), self.assertRaisesRegex(
                ValidationError, "public_endpoint_rejected"
            ):
                EndpointPolicy.resolve(url)

    def test_lan_requires_exact_transmission_confirmation(self) -> None:
        url = "http://192.168.1.20:7860"
        with self.assertRaises(ValidationError) as raised:
            EndpointPolicy.resolve(url)
        self.assertEqual(raised.exception.code, "lan_confirmation_required")
        self.assertEqual(raised.exception.details["confirmation"], f"transmit:{url}")

        confirmed = EndpointPolicy.resolve(url, f"transmit:{url}")

        self.assertEqual(confirmed["class"], "lan")
        self.assertEqual(confirmed["base_url"], url)

    def test_rejects_credentials_dns_https_and_non_root_paths(self) -> None:
        invalid = (
            "https://127.0.0.1:7860",
            "http://user:password@127.0.0.1:7860",
            "http://image-host.local:7860",
            "http://127.0.0.1:7860/api",
            "http://127.0.0.1:7860?token=secret",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaisesRegex(
                ValidationError, "invalid_backend_endpoint"
            ):
                EndpointPolicy.resolve(url)


class BoundedJsonClientTests(unittest.TestCase):
    def test_reads_and_posts_json_on_the_frozen_origin(self) -> None:
        with FakeBackendServer() as server:
            server.routes[("GET", "/status")] = FakeResponse.json({"ready": True})
            server.routes[("POST", "/prompt")] = FakeResponse.json({"job_id": "1"})
            client = BoundedJsonClient(server.url, max_bytes=1024)

            self.assertEqual(client.get_json("/status"), {"ready": True})
            self.assertEqual(client.post_json("/prompt", {"prompt": "sea"}), {"job_id": "1"})

            posted = server.requests[1]
            self.assertEqual(posted["path"], "/prompt")
            self.assertEqual(posted["body"], b'{"prompt":"sea"}')

    def test_rejects_absolute_or_ambiguous_request_paths(self) -> None:
        client = BoundedJsonClient("http://127.0.0.1:7860")
        for path in ("status", "//8.8.8.8/status", "http://8.8.8.8/status", "/safe\\..\\escape"):
            with self.subTest(path=path), self.assertRaisesRegex(
                ValidationError, "invalid_backend_path"
            ):
                client.get_json(path)

    def test_rejects_oversized_response_before_json_decode(self) -> None:
        with FakeBackendServer() as server:
            server.routes[("GET", "/large")] = FakeResponse(body=b"x" * 17)
            client = BoundedJsonClient(server.url, max_bytes=16)

            with self.assertRaisesRegex(ArtifactError, "backend_response_too_large"):
                client.get_json("/large")

    def test_malformed_json_and_http_errors_are_structured(self) -> None:
        with FakeBackendServer() as server:
            server.routes[("GET", "/bad-json")] = FakeResponse(body=b"{")
            server.routes[("GET", "/failure")] = FakeResponse.json(
                {"private": "body must not leak"},
                status=500,
            )
            client = BoundedJsonClient(server.url)

            with self.assertRaisesRegex(ArtifactError, "invalid_backend_json"):
                client.get_json("/bad-json")
            with self.assertRaises(StateError) as raised:
                client.get_json("/failure")
            self.assertEqual(raised.exception.code, "backend_request_failed")
            self.assertEqual(raised.exception.details, {"status": 500})
            self.assertNotIn("private", str(raised.exception))

    def test_cross_origin_redirect_is_rejected_without_contacting_target(self) -> None:
        with FakeBackendServer() as server:
            server.routes[("GET", "/redirect")] = FakeResponse(
                status=302,
                headers={"Location": "http://192.0.2.1:9/private"},
            )
            client = BoundedJsonClient(server.url, timeout=0.25)

            with self.assertRaisesRegex(StateError, "backend_redirect_rejected"):
                client.get_json("/redirect")


class BackendRegistryTests(unittest.TestCase):
    def test_general_layout_capability_preserves_regional_alias(self) -> None:
        comfyui = FakeAdapter("comfyui")
        registry = BackendRegistry([comfyui])

        self.assertEqual(
            registry.layout_capability("copy-subject-two-stage-v1"),
            comfyui.layout_capability("copy-subject-two-stage-v1"),
        )
        self.assertEqual(
            registry.regional_layout_capability("copy-subject-v1"),
            comfyui.layout_capability("copy-subject-v1"),
        )

    def test_dispatches_only_registered_adapters_or_explicit_compatibility_runners(self) -> None:
        webui = FakeAdapter("webui")
        registry = BackendRegistry(
            [webui],
            {"diffusers": lambda request: {"backend": "diffusers", "request": request}},
        )

        self.assertIs(registry.get("webui"), webui)
        self.assertEqual(registry.generate({"backend": "webui"})["backend"], "webui")
        self.assertEqual(registry.generate({"backend": "diffusers"})["backend"], "diffusers")
        with self.assertRaisesRegex(ValidationError, "unsupported_backend"):
            registry.generate({"backend": "plugin"})

    def test_duplicate_adapter_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "duplicate_backend_adapter"):
            BackendRegistry([FakeAdapter("webui"), FakeAdapter("webui")])


if __name__ == "__main__":
    unittest.main()
