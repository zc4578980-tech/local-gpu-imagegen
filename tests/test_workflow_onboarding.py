from __future__ import annotations

import copy
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen.errors import AssetEngineError, ValidationError  # noqa: E402
from local_gpu_imagegen.workflow_onboarding import (  # noqa: E402
    WorkflowOnboarding,
    infer_workflow_binding,
)
from local_gpu_imagegen.workflow_templates import (  # noqa: E402
    WorkflowTemplateRegistry,
    validate_imported_workflow,
    workflow_component_bindings,
)


def shipped(name: str) -> dict[str, object]:
    return json.loads(
        (ROOT / "workflows" / "comfyui" / name).read_text(encoding="utf-8")
    )


def remap_graph(graph: dict[str, object], seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    old_ids = list(graph)
    new_ids = [f"node-{value}" for value in rng.sample(range(100, 999), len(old_ids))]
    mapping = dict(zip(old_ids, new_ids, strict=True))
    items = []
    for old_id, node in graph.items():
        changed = copy.deepcopy(node)
        for key, value in changed["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and value[0] in mapping:
                changed["inputs"][key] = [mapping[value[0]], value[1]]
        items.append((mapping[old_id], changed))
    rng.shuffle(items)
    return dict(items)


def comfy_record(
    backend_model_id: str,
    loader_class: str,
    loader_input: str,
    *,
    endpoint: str = "http://127.0.0.1:8188",
) -> dict[str, object]:
    return {
        "backend": "comfyui",
        "endpoint_identity": endpoint,
        "backend_model_id": backend_model_id,
        "format": "comfyui-choice",
        "byte_size": None,
        "modified_ns": None,
        "sha256": None,
        "identity_strength": "backend_binding",
        "metadata": {"loader_class": loader_class, "loader_input": loader_input},
    }


class WorkflowBindingInferenceTests(unittest.TestCase):
    def test_infers_single_checkpoint_and_passes_authoritative_validator(self) -> None:
        document = shipped("sd15-txt2img-v1.json")
        inferred = infer_workflow_binding(document["graph"])
        validated = validate_imported_workflow(
            document["graph"],
            inferred["binding"],
            ["model.safetensors"],
        )
        self.assertEqual(inferred["topology"], "single_checkpoint")
        self.assertEqual(inferred["output_node"], validated["output_node"])
        self.assertEqual(inferred["binding"], validated["binding"])

    def test_infers_split_model_after_node_and_key_randomization(self) -> None:
        document = shipped("z-image-turbo-txt2img-v1.json")
        for seed in range(10):
            graph = remap_graph(document["graph"], seed)
            inferred = infer_workflow_binding(graph)
            primary_names = [
                item["backend_model_id"]
                for item in inferred["components"]
                if item["role"] == "primary_model"
            ]
            validated = validate_imported_workflow(
                graph,
                inferred["binding"],
                primary_names,
            )
            self.assertEqual(inferred["topology"], "split_model")
            self.assertEqual(inferred["binding"], validated["binding"])
            self.assertEqual(
                [item["role"] for item in inferred["components"]],
                ["primary_model", "text_encoder", "vae"],
            )

    def test_duplicate_semantic_roles_fail_closed(self) -> None:
        base = shipped("sd15-txt2img-v1.json")["graph"]
        cases = {
            "primary_model": lambda graph: graph.update(
                {"loader-copy": copy.deepcopy(graph["4"])}
            ),
            "sampler": lambda graph: graph.update(
                {"sampler-copy": copy.deepcopy(graph["3"])}
            ),
            "latent_source": lambda graph: graph.update(
                {"latent-copy": copy.deepcopy(graph["5"])}
            ),
            "owned_output": lambda graph: graph.update(
                {"output-copy": copy.deepcopy(graph["9"])}
            ),
        }
        for role, mutate in cases.items():
            graph = copy.deepcopy(base)
            mutate(graph)
            with self.subTest(role=role), self.assertRaises(ValidationError) as raised:
                infer_workflow_binding(graph)
            self.assertIn(
                raised.exception.code,
                {"ambiguous_workflow_binding", "unsupported_workflow_topology"},
            )

    def test_img2img_inpaint_regional_and_two_stage_are_not_candidates(self) -> None:
        cases = (
            ("img2img", "VAEEncode", {"pixels": ["8", 0], "vae": ["4", 2]}),
            (
                "inpaint",
                "VAEEncodeForInpaint",
                {
                    "pixels": ["8", 0],
                    "vae": ["4", 2],
                    "mask": ["8", 0],
                    "grow_mask_by": 6,
                },
            ),
            (
                "regional",
                "ConditioningCombine",
                {"conditioning_1": ["6", 0], "conditioning_2": ["7", 0]},
            ),
            ("two_stage", "SolidMask", {"value": 1.0, "width": 512, "height": 512}),
        )
        for label, class_type, inputs in cases:
            graph = shipped("sd15-txt2img-v1.json")["graph"]
            graph["excluded"] = {"class_type": class_type, "inputs": inputs}
            with self.subTest(label=label), self.assertRaises(ValidationError):
                infer_workflow_binding(graph)

    def test_disconnected_or_cross_wired_execution_path_is_rejected(self) -> None:
        document = shipped("sd15-txt2img-v1.json")
        base = document["graph"]
        binding = {
            **document["bindings"],
            "output": [document["output_node"]],
        }
        sampler_id = binding["seed"][0]
        model_id = binding["model"][0]
        positive_id = binding["positive_prompt"][0]
        negative_id = binding["negative_prompt"][0]
        latent_id = binding["width"][0]
        decoder_id = next(
            node_id
            for node_id, node in base.items()
            if node["class_type"] == "VAEDecode"
        )
        output_id = document["output_node"]
        cases = (
            (sampler_id, "model", [latent_id, 0]),
            (sampler_id, "positive", [negative_id, 0]),
            (sampler_id, "negative", [positive_id, 0]),
            (sampler_id, "latent_image", [positive_id, 0]),
            (decoder_id, "samples", [latent_id, 0]),
            (decoder_id, "vae", [positive_id, 0]),
            (output_id, "images", [sampler_id, 0]),
        )
        for node_id, field, edge in cases:
            graph = copy.deepcopy(base)
            graph[node_id]["inputs"][field] = edge
            with self.subTest(field=field), self.assertRaises(ValidationError):
                infer_workflow_binding(graph)
        self.assertEqual(base[model_id]["class_type"], "CheckpointLoaderSimple")


class WorkflowOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_dir = self.root / "state"
        self.inventory: list[dict[str, object]] = []
        self.registry = WorkflowTemplateRegistry(
            ROOT / "workflows" / "comfyui",
            self.state_dir,
        )
        self.onboarding = WorkflowOnboarding(
            self.registry,
            lambda: copy.deepcopy(self.inventory),
        )
        self.single_graph = shipped("sd15-txt2img-v1.json")["graph"]
        self.split_graph = shipped("z-image-turbo-txt2img-v1.json")["graph"]
        self.single_path = self.write_json("single.json", self.single_graph)
        self.split_path = self.write_json("split.json", self.split_graph)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_json(
        self,
        filename: str,
        value: object,
        *,
        compact: bool = False,
    ) -> Path:
        path = self.root / filename
        path.write_text(
            json.dumps(
                value,
                sort_keys=not compact,
                separators=(",", ":") if compact else None,
            ),
            encoding="utf-8",
        )
        return path

    def use_exact_single_inventory(self) -> None:
        component = workflow_component_bindings(self.single_graph)[0]
        self.inventory[:] = [
            comfy_record(
                component["backend_model_id"],
                component["loader_class"],
                component["loader_input"],
            )
        ]

    def reset_single_case(self) -> None:
        self.write_json("single.json", self.single_graph)
        self.use_exact_single_inventory()

    def change_prompt_text(self, path: Path) -> None:
        graph = json.loads(path.read_text(encoding="utf-8"))
        inferred = infer_workflow_binding(graph)
        node_id = inferred["binding"]["positive_prompt"][0]
        graph[node_id]["inputs"]["text"] = "changed"
        self.write_json(path.name, graph)

    def change_inventory_endpoint(self) -> None:
        changed = copy.deepcopy(self.inventory[0])
        changed["endpoint_identity"] = "http://127.0.0.1:8288"
        self.inventory[:] = [changed]

    def ambiguous_inventory_cases(self) -> list[list[dict[str, object]]]:
        component = workflow_component_bindings(self.split_graph)[0]
        exact = comfy_record(
            component["backend_model_id"],
            component["loader_class"],
            component["loader_input"],
        )
        duplicate = copy.deepcopy(exact)
        duplicate["endpoint_identity"] = "http://127.0.0.1:8288"
        wrong_loader = copy.deepcopy(exact)
        wrong_loader["metadata"] = {
            "loader_class": "CheckpointLoaderSimple",
            "loader_input": "ckpt_name",
        }
        return [[exact, duplicate], [wrong_loader]]

    def test_bare_graph_and_prompt_wrapper_share_semantic_hash_but_not_source_hash(
        self,
    ) -> None:
        document = shipped("sd15-txt2img-v1.json")
        graph = document["graph"]
        bare = self.write_json("bare.json", graph, compact=True)
        wrapped = self.write_json("wrapped.json", {"prompt": graph, "ignored": {"x": 1}})
        self.use_exact_single_inventory()

        bare_result = self.onboarding.inspect(bare)
        wrapped_result = self.onboarding.inspect(wrapped)

        self.assertNotEqual(bare_result["source_sha256"], wrapped_result["source_sha256"])
        self.assertEqual(bare_result["workflow_sha256"], wrapped_result["workflow_sha256"])
        self.assertNotEqual(
            bare_result.get("proposal_digest"),
            wrapped_result.get("proposal_digest"),
        )

    def test_offline_inspection_is_diagnostic_and_has_no_confirmation(self) -> None:
        path = self.write_json("workflow.json", shipped("sd15-txt2img-v1.json")["graph"])
        result = self.onboarding.inspect(path)

        self.assertEqual(result["status"], "diagnostic")
        self.assertFalse(result["registrable"])
        self.assertNotIn("proposal_digest", result)
        self.assertNotIn("confirmation", result)
        self.assertIn("local_gpu_discover_models", result["recoverable_next_actions"])
        self.assertFalse((self.state_dir / "workflows" / "registered").exists())

    def test_ui_format_and_multiple_prompt_graphs_are_actionable_rejections(self) -> None:
        ui = self.write_json("ui.json", {"nodes": [], "links": [], "widgets_values": []})
        with self.assertRaises(ValidationError) as raised:
            self.onboarding.inspect(ui)
        self.assertEqual(raised.exception.code, "unsupported_workflow_envelope")
        self.assertIn("developer mode", str(raised.exception).lower())

        wrapper = self.write_json(
            "multiple.json",
            {"prompt": self.single_graph, "other": self.single_graph},
        )
        with self.assertRaises(ValidationError) as multiple:
            self.onboarding.inspect(wrapper)
        self.assertEqual(multiple.exception.code, "unsupported_workflow_envelope")

    def test_unsafe_or_unreadable_sources_fail_before_inspection(self) -> None:
        malformed = self.root / "malformed.json"
        malformed.write_bytes(b"\xff\xfe")
        oversized = self.root / "oversized.json"
        oversized.write_bytes(b" " * ((2 * 1024 * 1024) + 1))
        directory = self.root / "directory.json"
        directory.mkdir()
        cases = (malformed, oversized, directory)
        for path in cases:
            with self.subTest(path=path), self.assertRaises(AssetEngineError) as raised:
                self.onboarding.inspect(path)
            self.assertEqual(raised.exception.code, "invalid_workflow_source")
        self.assertFalse((self.state_dir / "workflows" / "registered").exists())

    def test_symlink_source_is_rejected_when_supported(self) -> None:
        link = self.root / "linked.json"
        try:
            link.symlink_to(self.single_path)
        except OSError as error:
            self.skipTest(f"link creation unavailable: {error}")
        with self.assertRaises(AssetEngineError) as raised:
            self.onboarding.inspect(link)
        self.assertEqual(raised.exception.code, "invalid_workflow_source")

    def test_exact_single_inventory_match_is_registerable(self) -> None:
        document = shipped("sd15-txt2img-v1.json")
        component = workflow_component_bindings(document["graph"])[0]
        self.inventory[:] = [
            comfy_record(
                component["backend_model_id"],
                component["loader_class"],
                component["loader_input"],
            )
        ]
        result = self.onboarding.inspect(
            self.write_json("single.json", document["graph"])
        )

        self.assertEqual(result["status"], "registerable")
        self.assertTrue(result["registrable"])
        self.assertRegex(result["proposal_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            result["confirmation"],
            f"register_workflow:{result['source_sha256']}:{result['proposal_digest']}",
        )

    def test_exact_split_inventory_match_is_registerable(self) -> None:
        components = workflow_component_bindings(self.split_graph)
        self.inventory[:] = [
            comfy_record(
                component["backend_model_id"],
                component["loader_class"],
                component["loader_input"],
            )
            for component in components
        ]

        result = self.onboarding.inspect(self.split_path)

        self.assertEqual(result["status"], "registerable")
        self.assertEqual(
            [item["role"] for item in result["components"]],
            ["primary_model", "text_encoder", "vae"],
        )
        self.assertTrue(all("identity_token" in item for item in result["components"]))

    def test_duplicate_or_cross_endpoint_inventory_never_emits_confirmation(self) -> None:
        for inventory in self.ambiguous_inventory_cases():
            self.inventory[:] = inventory
            result = self.onboarding.inspect(self.split_path)
            self.assertFalse(result["registrable"])
            self.assertNotIn("confirmation", result)

    def test_split_components_from_different_endpoints_are_diagnostic(self) -> None:
        components = workflow_component_bindings(self.split_graph)
        self.inventory[:] = [
            comfy_record(
                component["backend_model_id"],
                component["loader_class"],
                component["loader_input"],
                endpoint=f"http://127.0.0.1:{8188 + index}",
            )
            for index, component in enumerate(components)
        ]

        result = self.onboarding.inspect(self.split_path)

        self.assertEqual(result["status"], "diagnostic")
        self.assertFalse(result["registrable"])
        self.assertNotIn("confirmation", result)
