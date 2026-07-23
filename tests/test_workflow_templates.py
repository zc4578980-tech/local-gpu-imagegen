from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import ArtifactError, ConflictError, ValidationError  # noqa: E402
from local_gpu_imagegen.workflow_templates import (  # noqa: E402
    WorkflowTemplateRegistry,
    validate_imported_workflow,
)


MODEL = "anything-v5.safetensors"
SDXL_MODEL = "sd_xl_base_1.0.safetensors"
Z_IMAGE_MODEL = "z_image_turbo_nvfp4.safetensors"
ANIMA_MODEL = "anima-aesthetic-v1.1.safetensors"


def parameters(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "positive_prompt": "calm sea",
        "negative_prompt": "artifacts",
        "seed": 42,
        "steps": 24,
        "guidance_scale": 5.5,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 768,
        "height": 512,
    }
    value.update(changes)
    return value


def binding(**changes: object) -> dict[str, list[str]]:
    value = {
        "model": ["4", "inputs", "ckpt_name"],
        "positive_prompt": ["6", "inputs", "text"],
        "negative_prompt": ["7", "inputs", "text"],
        "seed": ["3", "inputs", "seed"],
        "steps": ["3", "inputs", "steps"],
        "guidance_scale": ["3", "inputs", "cfg"],
        "sampler": ["3", "inputs", "sampler_name"],
        "scheduler": ["3", "inputs", "scheduler"],
        "width": ["5", "inputs", "width"],
        "height": ["5", "inputs", "height"],
        "output": ["9"],
    }
    value.update(changes)
    return value


def safe_graph() -> dict[str, object]:
    template = json.loads(
        (ROOT / "workflows" / "comfyui" / "sd15-txt2img-v1.json").read_text(
            encoding="utf-8"
        )
    )
    return copy.deepcopy(template["graph"])


def graph_with_node(
    node_id: str,
    class_type: str,
    inputs: dict[str, object],
) -> dict[str, object]:
    graph = safe_graph()
    graph[node_id] = {"class_type": class_type, "inputs": inputs}
    return graph


def graph_with_save_prefix(prefix: str) -> dict[str, object]:
    graph = safe_graph()
    graph["9"]["inputs"]["filename_prefix"] = prefix
    return graph


class WorkflowTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temporary_directory.name) / "state"
        self.registry = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            self.state_dir,
        )
        self.safe_source = Path(self.temporary_directory.name) / "safe.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_safe_source(self) -> None:
        self.safe_source.write_text(json.dumps(safe_graph()), encoding="utf-8")

    def test_shipped_template_renders_only_bound_parameters(self) -> None:
        resolved = self.registry.resolve(
            "sd15-txt2img",
            MODEL,
            "txt2img",
            parameters(),
        )

        self.assertEqual(resolved["template_version"], 1)
        self.assertEqual(resolved["operation"], "txt2img")
        self.assertEqual(resolved["model_family"], "sd15")
        self.assertEqual(resolved["output_node"], "9")
        self.assertRegex(resolved["workflow_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(resolved["graph"]["4"]["inputs"]["ckpt_name"], MODEL)
        self.assertEqual(resolved["graph"]["3"]["inputs"]["steps"], 24)
        self.assertEqual(resolved["graph"]["3"]["inputs"]["cfg"], 5.5)
        self.assertEqual(resolved["graph"]["5"]["inputs"]["width"], 768)

    def test_reviewed_sdxl_template_renders_native_family_and_settings(self) -> None:
        try:
            resolved = self.registry.resolve(
                "sdxl-txt2img",
                SDXL_MODEL,
                "txt2img",
                parameters(
                    steps=30,
                    guidance_scale=7.0,
                    sampler="dpmpp_2m",
                    scheduler="karras",
                    width=1024,
                    height=1024,
                ),
            )
        except ValidationError as error:
            self.fail(f"Reviewed SDXL workflow is unavailable: {error}")

        graph = resolved["graph"]
        self.assertEqual(resolved["template_version"], 1)
        self.assertEqual(resolved["model_family"], "sdxl")
        self.assertEqual(graph["4"]["inputs"]["ckpt_name"], SDXL_MODEL)
        self.assertEqual(graph["3"]["inputs"]["steps"], 30)
        self.assertEqual(graph["3"]["inputs"]["cfg"], 7.0)
        self.assertEqual(graph["3"]["inputs"]["sampler_name"], "dpmpp_2m")
        self.assertEqual(graph["3"]["inputs"]["scheduler"], "karras")
        self.assertEqual(graph["5"]["inputs"]["width"], 1024)
        self.assertEqual(graph["5"]["inputs"]["height"], 1024)
        self.assertEqual(
            graph[resolved["output_node"]]["inputs"]["filename_prefix"],
            "local-gpu-imagegen",
        )
        self.assertNotIn("layout_mode", resolved)
        self.assertEqual(
            resolved["workflow_sha256"],
            "05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e",
        )

    def test_reviewed_sdxl_regional_template_binds_all_confirmed_values(self) -> None:
        layout = {
            "mode": "copy-subject-v1",
            "copy_region": {
                "x": 0.0,
                "y": 0.0,
                "width": 0.45,
                "height": 1.0,
            },
            "subject_region": {
                "x": 0.68,
                "y": 0.0,
                "width": 0.30,
                "height": 1.0,
            },
        }
        conditioning = {
            "copy_prompt": "empty dark copy space",
            "copy_strength": 1.15,
            "subject_prompt": "complete telescope",
            "subject_strength": 1.25,
        }

        rendered = self.registry.resolve(
            "sdxl-regional-txt2img",
            SDXL_MODEL,
            "txt2img",
            parameters(),
            regional_layout=layout,
            regional_conditioning=conditioning,
        )

        graph = rendered["graph"]
        self.assertEqual(rendered["layout_mode"], "copy-subject-v1")
        self.assertEqual(graph["8"]["inputs"]["text"], "empty dark copy space")
        self.assertEqual(
            graph["10"]["inputs"],
            {
                "conditioning": ["8", 0],
                "width": 0.45,
                "height": 1.0,
                "x": 0.0,
                "y": 0.0,
                "strength": 1.15,
            },
        )
        self.assertEqual(graph["11"]["inputs"]["text"], "complete telescope")
        self.assertEqual(
            graph["12"]["inputs"],
            {
                "conditioning": ["11", 0],
                "width": 0.30,
                "height": 1.0,
                "x": 0.68,
                "y": 0.0,
                "strength": 1.25,
            },
        )

    def test_regional_template_requires_data_and_standard_rejects_it(self) -> None:
        layout = {
            "mode": "copy-subject-v1",
            "copy_region": {"x": 0.0, "y": 0.0, "width": 0.45, "height": 1.0},
            "subject_region": {"x": 0.68, "y": 0.0, "width": 0.30, "height": 1.0},
        }
        conditioning = {
            "copy_prompt": "empty dark copy space",
            "copy_strength": 1.15,
            "subject_prompt": "complete telescope",
            "subject_strength": 1.25,
        }
        with self.assertRaisesRegex(ValidationError, "invalid_regional_layout"):
            self.registry.resolve(
                "sdxl-regional-txt2img",
                SDXL_MODEL,
                "txt2img",
                parameters(),
            )
        with self.assertRaisesRegex(ValidationError, "invalid_regional_conditioning"):
            self.registry.resolve(
                "sdxl-txt2img",
                SDXL_MODEL,
                "txt2img",
                parameters(),
                regional_layout=layout,
                regional_conditioning=conditioning,
            )

    def test_regional_nodes_remain_forbidden_in_imported_workflows(self) -> None:
        graph = safe_graph()
        graph["20"] = {
            "class_type": "ConditioningCombine",
            "inputs": {
                "conditioning_1": ["6", 0],
                "conditioning_2": ["7", 0],
            },
        }

        with self.assertRaisesRegex(ValidationError, "unsafe_comfy_workflow"):
            validate_imported_workflow(graph, binding(), [MODEL])

    def test_inspect_shipped_regional_template_keeps_reviewed_static_values(self) -> None:
        inspected = self.registry.inspect_shipped(
            "sdxl-regional-txt2img",
            SDXL_MODEL,
            "txt2img",
            parameters(),
        )

        self.assertEqual(inspected["layout_mode"], "copy-subject-v1")
        self.assertEqual(inspected["graph"]["10"]["inputs"]["width"], 0.45)
        self.assertEqual(inspected["graph"]["12"]["inputs"]["strength"], 1.25)

    def test_reviewed_split_model_templates_render_exact_model_contracts(self) -> None:
        cases = (
            (
                "z-image-turbo-txt2img",
                Z_IMAGE_MODEL,
                parameters(
                    steps=8,
                    guidance_scale=1.0,
                    sampler="res_multistep",
                    scheduler="simple",
                    width=768,
                    height=768,
                ),
                "z-image",
                "qwen_3_4b_fp4_mixed.safetensors",
                "ae.safetensors",
            ),
            (
                "anima-txt2img",
                ANIMA_MODEL,
                parameters(
                    steps=30,
                    guidance_scale=4.0,
                    sampler="er_sde",
                    scheduler="simple",
                    width=768,
                    height=768,
                ),
                "anima",
                "qwen_3_06b_base.safetensors",
                "qwen_image_vae.safetensors",
            ),
        )
        for template_id, model, settings, family, clip, vae in cases:
            with self.subTest(template_id=template_id):
                resolved = self.registry.resolve(template_id, model, "txt2img", settings)
                graph = resolved["graph"]
                self.assertEqual(resolved["model_family"], family)
                self.assertEqual(graph["1"]["inputs"]["unet_name"], model)
                self.assertEqual(graph["2"]["inputs"]["clip_name"], clip)
                self.assertEqual(graph["3"]["inputs"]["vae_name"], vae)
                self.assertEqual(graph[resolved["output_node"]]["inputs"]["filename_prefix"], "local-gpu-imagegen")

    def test_split_model_routes_reject_unreviewed_loader_settings(self) -> None:
        document = json.loads(
            (ROOT / "workflows" / "comfyui" / "z-image-turbo-txt2img-v1.json").read_text(
                encoding="utf-8"
            )
        )
        graph = document["graph"]
        graph_binding = {**document["bindings"], "output": [document["output_node"]]}
        mutations = (
            ("1", "weight_dtype", "fp8_e4m3fn"),
            ("2", "type", "qwen_image"),
            ("8", "shift", 4.0),
        )
        for node_id, field, value in mutations:
            changed = copy.deepcopy(graph)
            changed[node_id]["inputs"][field] = value
            with self.subTest(node_id=node_id, field=field), self.assertRaisesRegex(
                ValidationError,
                "unsafe_comfy_workflow",
            ):
                validate_imported_workflow(changed, graph_binding, [Z_IMAGE_MODEL])

    def test_rejects_every_unsafe_fixture(self) -> None:
        unsafe = {
            "code": graph_with_node("10", "PythonScript", {"code": "print(1)"}),
            "http": graph_with_node(
                "10",
                "HTTPDownload",
                {"url": "http://127.0.0.1/file"},
            ),
            "write": graph_with_save_prefix("C:/outside/result"),
            "unknown": graph_with_node("10", "UnreviewedCustomNode", {}),
            "ambiguous": graph_with_node(
                "10",
                "SaveImage",
                {"filename_prefix": "local-gpu-imagegen", "images": ["8", 0]},
            ),
        }
        for name, graph in unsafe.items():
            source = self.state_dir / f"{name}.json"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(json.dumps(graph), encoding="utf-8")
            with self.subTest(name=name), self.assertRaisesRegex(
                ValidationError,
                "unsafe_comfy_workflow",
            ):
                self.registry.register_import(source, binding(), [MODEL])

    def test_rejects_unbound_fields_resource_overruns_and_unknown_model(self) -> None:
        invalid: list[tuple[dict[str, object], dict[str, list[str]], list[str]]] = []
        extra_input = safe_graph()
        extra_input["3"]["inputs"]["command"] = "ignored"
        invalid.append((extra_input, binding(), [MODEL]))
        too_many_steps = safe_graph()
        too_many_steps["3"]["inputs"]["steps"] = 81
        invalid.append((too_many_steps, binding(), [MODEL]))
        invalid.append((safe_graph(), binding(), ["different.safetensors"]))
        missing_binding = binding()
        del missing_binding["seed"]
        invalid.append((safe_graph(), missing_binding, [MODEL]))

        for graph, graph_binding, models in invalid:
            with self.subTest(graph=graph, graph_binding=graph_binding, models=models):
                with self.assertRaisesRegex(ValidationError, "unsafe_comfy_workflow"):
                    validate_imported_workflow(graph, graph_binding, models)

    def test_import_is_normalized_copied_and_independent_of_source(self) -> None:
        self.write_safe_source()

        registered = self.registry.register_import(
            self.safe_source,
            binding(),
            [MODEL],
        )
        copied = Path(registered["local_path"])
        self.assertTrue(copied.is_relative_to(self.state_dir))
        self.assertNotEqual(copied, self.safe_source)
        self.safe_source.write_text("{}", encoding="utf-8")

        loaded = self.registry.load_registered(registered["template_id"])

        self.assertEqual(loaded["workflow_sha256"], registered["workflow_sha256"])
        self.assertEqual(loaded["graph"]["4"]["inputs"]["ckpt_name"], MODEL)

    def test_tampered_registered_copy_invalidates_registration(self) -> None:
        self.write_safe_source()
        registered = self.registry.register_import(
            self.safe_source,
            binding(),
            [MODEL],
        )
        Path(registered["local_path"]).write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(ConflictError, "workflow_registration_drifted"):
            self.registry.load_registered(registered["template_id"])

    def test_import_rejects_oversized_or_malformed_sources(self) -> None:
        oversized = Path(self.temporary_directory.name) / "oversized.json"
        oversized.write_bytes(b" " * (2 * 1024 * 1024 + 1))
        malformed = Path(self.temporary_directory.name) / "malformed.json"
        malformed.write_text("not-json", encoding="utf-8")

        with self.assertRaisesRegex(ArtifactError, "invalid_workflow_source"):
            self.registry.register_import(oversized, binding(), [MODEL])
        with self.assertRaisesRegex(ArtifactError, "invalid_workflow_source"):
            self.registry.register_import(malformed, binding(), [MODEL])

    def test_resolve_rejects_unbound_or_over_budget_parameters(self) -> None:
        invalid = (
            parameters(extra="silent"),
            parameters(steps=81),
            parameters(width=770),
            parameters(seed=-1),
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValidationError,
                "invalid_workflow_parameters",
            ):
                self.registry.resolve("sd15-txt2img", MODEL, "txt2img", value)


if __name__ == "__main__":
    unittest.main()
