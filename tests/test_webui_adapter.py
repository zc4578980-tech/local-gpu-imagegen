from __future__ import annotations

import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.backends.webui import WebUIAdapter  # noqa: E402
from local_gpu_imagegen.errors import ArtifactError, ConflictError  # noqa: E402
from tests.fake_backend_server import FakeBackendServer, FakeResponse  # noqa: E402


FULL_HASH = "a" * 64
PNG_BYTES = b"adapter-test-png"
MODEL_TITLE = f"sd15\\anything-v5.safetensors [{FULL_HASH[:10]}]"


class WebUIAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary_directory.name) / "output.png"
        self.source = Path(self.temporary_directory.name) / "source.png"
        self.mask = Path(self.temporary_directory.name) / "mask.png"
        self.source.write_bytes(b"source-image")
        self.mask.write_bytes(b"mask-image")
        self.server_context = FakeBackendServer()
        self.server = self.server_context.__enter__()
        self.server.routes[("GET", "/sdapi/v1/options")] = FakeResponse.json({
            "sd_model_checkpoint": MODEL_TITLE,
        })
        self.server.routes[("GET", "/sdapi/v1/version")] = FakeResponse.json({
            "version": "1.10.1",
        })
        self.server.routes[("GET", "/sdapi/v1/sd-models")] = FakeResponse.json([
            {
                "title": MODEL_TITLE,
                "model_name": "anything-v5",
                "hash": FULL_HASH[:10],
                "sha256": FULL_HASH,
                "filename": "D:/private/models/anything-v5.safetensors",
            }
        ])
        self.server.routes[("POST", "/sdapi/v1/txt2img")] = self.generation_response
        self.server.routes[("POST", "/sdapi/v1/img2img")] = self.generation_response
        self.adapter = WebUIAdapter(self.server.url)

    def tearDown(self) -> None:
        self.server_context.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    @staticmethod
    def generation_response(_method: str, _path: str, body: bytes) -> FakeResponse:
        payload = json.loads(body.decode("utf-8"))
        return FakeResponse.json({
            "images": [base64.b64encode(PNG_BYTES).decode("ascii")],
            "info": json.dumps({
                "seed": payload.get("seed"),
                "sd_model_name": "anything-v5",
                "sd_model_hash": FULL_HASH[:10],
            }),
        })

    def discovered_model(self) -> dict[str, object]:
        return self.adapter.discover()[0]

    def request(
        self,
        *,
        mode: str = "txt2img",
        model: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "backend": "webui",
            "model": model or self.discovered_model(),
            "mode": mode,
            "positive_prompt": "calm sea, dawn",
            "negative_prompt": "artifacts",
            "width": 768,
            "height": 512,
            "steps": 24,
            "guidance_scale": 5.5,
            "sampler": "DPM++ 2M",
            "seed": 42,
            "source_path": str(self.source) if mode != "txt2img" else None,
            "mask_path": str(self.mask) if mode == "inpaint" else None,
            "strength": 0.45 if mode != "txt2img" else None,
            "output_path": str(self.output),
            "prompt_compiler_id": "sd15-tags-v1",
            "prompt_compiler_version": 1,
        }

    def test_probe_reports_backend_version_and_frozen_endpoint(self) -> None:
        report = self.adapter.probe()

        self.assertEqual(report["backend"], "webui")
        self.assertEqual(report["implementation"], "AUTOMATIC1111")
        self.assertEqual(report["version"], "1.10.1")
        self.assertTrue(report["ready"])
        self.assertEqual(report["endpoint_identity"], self.adapter.endpoint_identity)

    def test_discovery_reports_full_hash_without_switching_or_leaking_filename(self) -> None:
        records = self.adapter.discover()

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["backend_model_id"], MODEL_TITLE)
        self.assertEqual(record["sha256"], FULL_HASH)
        self.assertEqual(record["identity_strength"], "cryptographic")
        self.assertRegex(record["identity_token"], r"^model:[0-9a-f]{64}$")
        self.assertNotIn("D:/private", json.dumps(record))
        self.assertEqual(
            [(item["method"], item["path"]) for item in self.server.requests],
            [("GET", "/sdapi/v1/sd-models")],
        )

    def test_short_backend_hash_remains_private_backend_binding(self) -> None:
        self.server.routes[("GET", "/sdapi/v1/sd-models")] = FakeResponse.json([
            {"title": MODEL_TITLE, "model_name": "anything-v5", "hash": FULL_HASH[:10]},
        ])

        record = self.adapter.discover()[0]

        self.assertIsNone(record["sha256"])
        self.assertEqual(record["identity_strength"], "backend_binding")
        self.assertFalse(record["public_evidence_eligible"])

    def test_generation_uses_exact_checkpoint_and_returns_normalized_identity(self) -> None:
        model = self.discovered_model()
        self.server.requests.clear()

        result = self.adapter.generate(self.request(model=model))

        self.assertEqual(self.output.read_bytes(), PNG_BYTES)
        self.assertEqual(result["backend"], "webui")
        self.assertEqual(result["model"], MODEL_TITLE)
        self.assertEqual(result["model_identity_token"], model["identity_token"])
        self.assertEqual(result["identity_strength"], "cryptographic")
        self.assertEqual(result["endpoint_identity"], self.adapter.endpoint_identity)
        self.assertEqual(result["seed"], 42)
        self.assertEqual(
            [item["path"] for item in self.server.requests],
            ["/sdapi/v1/sd-models", "/sdapi/v1/options", "/sdapi/v1/txt2img"],
        )
        payload = json.loads(self.server.requests[-1]["body"].decode("utf-8"))
        self.assertEqual(payload["override_settings"], {"sd_model_checkpoint": MODEL_TITLE})
        self.assertTrue(payload["override_settings_restore_afterwards"])
        self.assertEqual(payload["batch_size"], 1)
        self.assertEqual(payload["n_iter"], 1)

    def test_missing_or_changed_confirmed_model_fails_before_post(self) -> None:
        discovered = self.discovered_model()
        missing = copy.deepcopy(discovered)
        missing["backend_model_id"] = "missing.safetensors"
        changed = copy.deepcopy(discovered)
        changed["identity_token"] = "model:" + "f" * 64
        for model in (missing, changed):
            self.server.requests.clear()
            with self.subTest(model=model), self.assertRaisesRegex(
                ConflictError, "backend_model_mismatch"
            ):
                self.adapter.generate(self.request(model=model))
            self.assertFalse(any(item["method"] == "POST" for item in self.server.requests))
            self.assertFalse(self.output.exists())

    def test_each_mode_maps_source_mask_and_strength_exactly(self) -> None:
        model = self.discovered_model()
        for mode in ("txt2img", "img2img", "inpaint"):
            with self.subTest(mode=mode):
                self.server.requests.clear()
                if self.output.exists():
                    self.output.unlink()

                result = self.adapter.generate(self.request(mode=mode, model=model))

                payload = json.loads(self.server.requests[-1]["body"].decode("utf-8"))
                self.assertEqual(result["mode"], mode)
                self.assertEqual("init_images" in payload, mode != "txt2img")
                self.assertEqual("mask" in payload, mode == "inpaint")
                if mode != "txt2img":
                    self.assertEqual(payload["denoising_strength"], 0.45)
                    self.assertEqual(
                        base64.b64decode(payload["init_images"][0]),
                        b"source-image",
                    )

    def test_unset_seed_retains_backend_selected_integer(self) -> None:
        model = self.discovered_model()

        def random_seed_response(_method: str, _path: str, body: bytes) -> FakeResponse:
            payload = json.loads(body.decode("utf-8"))
            self.assertEqual(payload["seed"], -1)
            return FakeResponse.json({
                "images": [base64.b64encode(PNG_BYTES).decode("ascii")],
                "info": json.dumps({
                    "seed": 987654,
                    "sd_model_name": "anything-v5",
                    "sd_model_hash": FULL_HASH[:10],
                }),
            })

        self.server.routes[("POST", "/sdapi/v1/txt2img")] = random_seed_response
        request = self.request(model=model)
        request["seed"] = None

        result = self.adapter.generate(request)

        self.assertEqual(result["seed"], 987654)

    def test_invalid_image_or_reported_model_does_not_write_output(self) -> None:
        model = self.discovered_model()
        invalid_responses = (
            {"images": ["not-base64"], "info": "{}"},
            {
                "images": [base64.b64encode(PNG_BYTES).decode("ascii")],
                "info": json.dumps({"sd_model_name": "different-model", "seed": 42}),
            },
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                self.server.routes[("POST", "/sdapi/v1/txt2img")] = FakeResponse.json(response)
                if self.output.exists():
                    self.output.unlink()
                with self.assertRaises((ArtifactError, ConflictError)):
                    self.adapter.generate(self.request(model=model))
                self.assertFalse(self.output.exists())

    def test_webui_job_control_is_explicitly_unsupported(self) -> None:
        self.assertEqual(
            self.adapter.cancel_or_query("synchronous", cancel=True),
            {
                "job_id": "synchronous",
                "state": "unsupported",
                "cancel_supported": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
