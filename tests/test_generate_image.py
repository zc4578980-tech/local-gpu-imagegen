from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import generate_image  # noqa: E402


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
    def test_delegates_exact_discovered_model_to_webui_adapter(self) -> None:
        model = {
            "backend": "webui",
            "endpoint_identity": "endpoint:test",
            "backend_model_id": "mock-model.safetensors",
            "format": ".safetensors",
            "byte_size": None,
            "modified_ns": None,
            "sha256": None,
            "identity_strength": "backend_binding",
            "metadata": {"model_name": "mock-model", "backend_hash": None},
            "public_evidence_eligible": False,
            "identity_token": "model:test",
        }
        expected = {
            "ok": True,
            "path": "output.png",
            "backend": "webui",
            "mode": "txt2img",
            "seed": 42,
            "width": 512,
            "height": 512,
        }
        adapter = Mock()
        adapter.discover.return_value = [model]
        adapter.probe.return_value = {"loaded_model": "mock-model.safetensors"}
        adapter.generate.return_value = expected
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(generate_image, "WebUIAdapter", return_value=adapter) as adapter_class:
                result = generate_image.generate_with_webui(webui_args(output_dir))

        self.assertIs(result, expected)
        adapter_class.assert_called_once_with("http://127.0.0.1:7860")
        request = adapter.generate.call_args.args[0]
        self.assertIs(request["model"], model)
        self.assertEqual(request["positive_prompt"], "a test image")
        self.assertEqual(request["output_path"], str(Path(output_dir) / "mock-result.png"))
        self.assertEqual(request["prompt_compiler_id"], "direct-v1")
        self.assertEqual(request["prompt_compiler_version"], 1)

    def test_mode_maps_source_and_mask_exactly(self) -> None:
        model = {"backend_model_id": "mock-model.safetensors"}
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
                    args.strength = 0.55 if mode != "txt2img" else None
                    adapter = Mock()
                    adapter.discover.return_value = [model]
                    adapter.probe.return_value = {"loaded_model": "mock-model.safetensors"}
                    adapter.generate.return_value = {"mode": mode}
                    with patch.object(generate_image, "WebUIAdapter", return_value=adapter):
                        result = generate_image.generate_with_webui(args)
                    request = adapter.generate.call_args.args[0]
                    self.assertEqual(request["source_path"], str(source) if mode != "txt2img" else None)
                    self.assertEqual(request["mask_path"], str(mask) if mode == "inpaint" else None)
                    self.assertEqual(request["strength"], 0.55 if mode != "txt2img" else None)
                    self.assertEqual(result["mode"], mode)

    def test_explicit_missing_model_is_rejected_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            args = webui_args(output_dir)
            args.model = "missing.safetensors"
            adapter = Mock()
            adapter.discover.return_value = [{"backend_model_id": "available.safetensors"}]
            with patch.object(generate_image, "WebUIAdapter", return_value=adapter):
                with self.assertRaisesRegex(RuntimeError, "not available"):
                    generate_image.generate_with_webui(args)
            adapter.generate.assert_not_called()

    def test_probe_failure_marks_webui_unavailable(self) -> None:
        with patch.object(generate_image, "WebUIAdapter", side_effect=OSError("offline")):
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
