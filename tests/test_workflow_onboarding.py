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
