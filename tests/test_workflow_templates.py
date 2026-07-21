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
