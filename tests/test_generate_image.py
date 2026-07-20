from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import generate_image  # noqa: E402


class FakeHttpResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def webui_args(output_dir: str) -> SimpleNamespace:
    return SimpleNamespace(
        prompt="a test image",
        negative_prompt="",
        width=512,
        height=512,
        steps=8,
        guidance_scale=6.0,
        sampler_name="Euler a",
        seed=42,
        model=None,
        mode="txt2img",
        input_image=None,
        mask_image=None,
        strength=None,
        webui_url="http://127.0.0.1:7860",
        output_dir=output_dir,
        filename="mock-result.png",
    )


class WebUiBackendTests(unittest.TestCase):
    def test_success_decodes_image_and_returns_metadata(self) -> None:
        png_bytes = b"mock-png-bytes"
        response = {
            "images": [base64.b64encode(png_bytes).decode("ascii")],
            "info": json.dumps({"seed": 42, "sd_model_name": "mock-model"}),
        }

        with tempfile.TemporaryDirectory() as output_dir:
            with patch("generate_image.urllib.request.urlopen", return_value=FakeHttpResponse(response)) as urlopen:
                result = generate_image.generate_with_webui(webui_args(output_dir))

            output_path = Path(str(result["path"]))
            self.assertEqual(output_path.read_bytes(), png_bytes)
            self.assertEqual(result["backend"], "webui")
            self.assertEqual(result["model"], "mock-model")
            self.assertEqual(result["seed"], 42)

            request = urlopen.call_args.args[0]
            sent_payload = json.loads(request.data.decode("utf-8"))
            self.assertTrue(request.full_url.endswith("/sdapi/v1/txt2img"))
            self.assertEqual(sent_payload["prompt"], "a test image")
            self.assertEqual(sent_payload["seed"], 42)

    def test_missing_images_is_reported_as_malformed_response(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch(
                "generate_image.urllib.request.urlopen",
                return_value=FakeHttpResponse({"info": "{}"}),
            ):
                with self.assertRaisesRegex(RuntimeError, "did not return an image"):
                    generate_image.generate_with_webui(webui_args(output_dir))

    def test_invalid_base64_is_reported_as_malformed_response(self) -> None:
        response = {"images": ["not-valid-base64!"], "info": "{}"}
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("generate_image.urllib.request.urlopen", return_value=FakeHttpResponse(response)):
                with self.assertRaisesRegex(RuntimeError, "invalid base64"):
                    generate_image.generate_with_webui(webui_args(output_dir))

    def test_timeout_marks_webui_unavailable(self) -> None:
        with patch("generate_image.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            self.assertFalse(generate_image.webui_available("http://127.0.0.1:7860"))


class DiffusersSafetyTests(unittest.TestCase):
    def test_hub_access_is_local_only_by_default(self) -> None:
        self.assertEqual(generate_image.hub_access_kwargs(False), {"local_files_only": True})

    def test_hub_access_can_be_explicitly_enabled(self) -> None:
        self.assertEqual(generate_image.hub_access_kwargs(True), {"local_files_only": False})


if __name__ == "__main__":
    unittest.main()
