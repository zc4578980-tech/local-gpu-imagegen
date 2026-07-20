from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
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


def diffusers_args(output_dir: str, mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        prompt="a test image",
        negative_prompt="avoid text",
        width=512,
        height=512,
        steps=8,
        guidance_scale=6.0,
        seed=42,
        model="local-model",
        mode=mode,
        input_image="source.png" if mode != "txt2img" else None,
        mask_image="mask.png" if mode == "inpaint" else None,
        strength=0.55 if mode != "txt2img" else None,
        scheduler="euler",
        allow_download=False,
        allow_cpu=False,
        disable_safety_checker=False,
        cpu_offload=False,
        vae_tiling=False,
        lora=[],
        lora_scale=1.0,
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
            self.assertEqual(sent_payload["batch_size"], 1)
            self.assertEqual(sent_payload["n_iter"], 1)
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 600)
            self.assertEqual(
                {"ok", "path", "backend", "mode", "seed", "width", "height"} - set(result),
                set(),
            )

    def test_mode_maps_source_and_mask_exactly(self) -> None:
        response = {"images": [base64.b64encode(b"image").decode("ascii")], "info": "{}"}
        with tempfile.TemporaryDirectory() as output_dir:
            source = Path(output_dir) / "source.png"
            mask = Path(output_dir) / "mask.png"
            source.write_bytes(b"source")
            mask.write_bytes(b"mask")
            for mode in ("txt2img", "img2img", "inpaint"):
                with self.subTest(mode=mode):
                    args = webui_args(output_dir)
                    args.mode = mode
                    args.input_image = str(source) if mode != "txt2img" else None
                    args.mask_image = str(mask) if mode == "inpaint" else None
                    with patch("generate_image.webui_api_post", return_value=response) as post:
                        result = generate_image.generate_with_webui(args)
                    endpoint = post.call_args.args[1]
                    payload = post.call_args.args[2]
                    self.assertEqual(endpoint, "/sdapi/v1/txt2img" if mode == "txt2img" else "/sdapi/v1/img2img")
                    self.assertEqual("init_images" in payload, mode != "txt2img")
                    self.assertEqual("mask" in payload, mode == "inpaint")
                    self.assertEqual(result["mode"], mode)

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

    def test_each_mode_uses_normalized_contract_and_exact_conditioning(self) -> None:
        required = {"ok", "path", "backend", "mode", "seed", "width", "height"}
        for mode, expected_class in (
            ("txt2img", "AutoPipelineForText2Image"),
            ("img2img", "AutoPipelineForImage2Image"),
            ("inpaint", "AutoPipelineForInpainting"),
        ):
            with self.subTest(mode=mode):
                calls: dict[str, object] = {}

                class FakeImage:
                    def save(self, path: Path) -> None:
                        Path(path).write_bytes(b"fake-png")

                class FakePipeline:
                    scheduler = SimpleNamespace(config={"original": True})

                    def to(self, device: str) -> "FakePipeline":
                        calls["device"] = device
                        return self

                    def enable_attention_slicing(self) -> None:
                        return None

                    def enable_vae_slicing(self) -> None:
                        return None

                    def __call__(self, **kwargs: object) -> SimpleNamespace:
                        calls["pipeline_call"] = kwargs
                        return SimpleNamespace(images=[FakeImage()])

                pipeline = FakePipeline()

                class PipelineFactory:
                    @classmethod
                    def from_pretrained(cls, model: str, **kwargs: object) -> FakePipeline:
                        calls["factory"] = expected_class
                        calls["model"] = model
                        calls["pretrained"] = kwargs
                        return pipeline

                class FakeScheduler:
                    @classmethod
                    def from_config(cls, config: object) -> str:
                        calls["scheduler_config"] = config
                        return "euler-scheduler"

                diffusers = ModuleType("diffusers")
                for class_name in (
                    "AutoPipelineForText2Image",
                    "AutoPipelineForImage2Image",
                    "AutoPipelineForInpainting",
                ):
                    setattr(diffusers, class_name, PipelineFactory if class_name == expected_class else type(class_name, (), {}))
                diffusers.EulerDiscreteScheduler = FakeScheduler
                torch = ModuleType("torch")
                torch.float16 = "float16"
                torch.float32 = "float32"
                torch.cuda = SimpleNamespace(is_available=lambda: True)

                class Generator:
                    def __init__(self, device: str) -> None:
                        calls["generator_device"] = device

                    def manual_seed(self, seed: int) -> "Generator":
                        calls["generator_seed"] = seed
                        return self

                torch.Generator = Generator
                with tempfile.TemporaryDirectory() as output_dir:
                    args = diffusers_args(output_dir, mode)
                    with patch.dict(sys.modules, {"torch": torch, "diffusers": diffusers}):
                        with patch("generate_image.load_condition_image", side_effect=lambda path, width, height: f"loaded:{path}"):
                            result = generate_image.generate_with_diffusers(args)

                self.assertEqual(calls["factory"], expected_class)
                self.assertEqual(calls["pretrained"]["local_files_only"], True)
                self.assertEqual(calls["generator_seed"], 42)
                self.assertEqual(calls["scheduler_config"], {"original": True})
                pipeline_call = calls["pipeline_call"]
                self.assertEqual("image" in pipeline_call, mode != "txt2img")
                self.assertEqual("mask_image" in pipeline_call, mode == "inpaint")
                if mode != "txt2img":
                    self.assertEqual(pipeline_call["image"], "loaded:source.png")
                if mode == "inpaint":
                    self.assertEqual(pipeline_call["mask_image"], "loaded:mask.png")
                self.assertEqual(required - set(result), set())
                self.assertEqual(result["backend"], "diffusers")
                self.assertEqual(result["mode"], mode)


if __name__ == "__main__":
    unittest.main()
