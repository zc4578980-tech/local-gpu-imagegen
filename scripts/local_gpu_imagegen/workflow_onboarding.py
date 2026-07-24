from __future__ import annotations

from .errors import ValidationError
from .workflow_templates import (
    MODEL_LOADER_INPUTS,
    workflow_component_bindings,
)


EXCLUDED_CLASSES = frozenset({
    "VAEEncode",
    "VAEEncodeForInpaint",
    "LoadImage",
    "LoadImageMask",
    "ConditioningSetAreaPercentage",
    "ConditioningCombine",
    "SolidMask",
    "MaskComposite",
    "FeatherMask",
    "ImageCompositeMasked",
    "MaskToImage",
})


class WorkflowOnboarding:
    pass


def _node(graph: dict[str, object], node_id: str) -> dict[str, object]:
    value = graph.get(node_id)
    if not isinstance(value, dict) or not isinstance(value.get("inputs"), dict):
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Workflow path references an invalid node.",
            {"candidate_node_ids": [node_id]},
        )
    return value


def _link(value: object, role: str) -> tuple[str, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not isinstance(value[0], str)
        or type(value[1]) is not int
        or value[1] < 0
    ):
        raise ValidationError(
            "ambiguous_workflow_binding",
            f"Workflow {role} is not one exact graph edge.",
            {"role": role, "candidate_node_ids": []},
        )
    return value[0], value[1]


def _only_class(
    graph: dict[str, object],
    classes: frozenset[str],
    role: str,
) -> tuple[str, dict[str, object]]:
    matches = sorted(
        (node_id, node)
        for node_id, node in graph.items()
        if isinstance(node, dict) and node.get("class_type") in classes
    )
    if len(matches) != 1:
        raise ValidationError(
            "ambiguous_workflow_binding",
            f"Workflow requires one unambiguous {role}.",
            {"role": role, "candidate_node_ids": [item[0] for item in matches]},
        )
    return matches[0]


def _walk_passthrough(
    graph: dict[str, object],
    edge: object,
    role: str,
    targets: frozenset[str],
    passthrough_input: dict[str, str],
) -> tuple[str, int]:
    seen: set[str] = set()
    node_id, slot = _link(edge, role)
    while True:
        if node_id in seen:
            raise ValidationError(
                "ambiguous_workflow_binding",
                f"Workflow {role} contains a cycle.",
                {"role": role, "candidate_node_ids": sorted(seen)},
            )
        seen.add(node_id)
        node = _node(graph, node_id)
        class_type = node.get("class_type")
        if class_type in targets:
            return node_id, slot
        input_name = passthrough_input.get(str(class_type))
        if input_name is None:
            raise ValidationError(
                "ambiguous_workflow_binding",
                f"Workflow {role} does not reach one reviewed source.",
                {"role": role, "candidate_node_ids": [node_id]},
            )
        node_id, slot = _link(node["inputs"].get(input_name), role)


def infer_workflow_binding(graph: object) -> dict[str, object]:
    if not isinstance(graph, dict) or not graph:
        raise ValidationError(
            "unsupported_workflow_envelope",
            "Workflow must contain one ComfyUI API graph object.",
        )
    classes = {
        node.get("class_type")
        for node in graph.values()
        if isinstance(node, dict)
    }
    excluded = sorted(item for item in classes if item in EXCLUDED_CLASSES)
    if excluded:
        raise ValidationError(
            "unsupported_workflow_operation",
            "Workflow onboarding supports ordinary txt2img only.",
            {"node_classes": excluded},
        )

    sampler_id, sampler = _only_class(graph, frozenset({"KSampler"}), "sampler")
    latent_id, _latent = _only_class(
        graph,
        frozenset({"EmptyLatentImage", "EmptySD3LatentImage"}),
        "latent_source",
    )
    decoder_id, decoder = _only_class(graph, frozenset({"VAEDecode"}), "decoder")
    output_id, output = _only_class(graph, frozenset({"SaveImage"}), "owned_output")

    if _link(sampler["inputs"].get("latent_image"), "latent_source")[0] != latent_id:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Sampler latent path is cross-wired.",
        )
    if _link(decoder["inputs"].get("samples"), "decoder")[0] != sampler_id:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Decoder sample path is cross-wired.",
        )
    if _link(output["inputs"].get("images"), "owned_output")[0] != decoder_id:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Owned output path is cross-wired.",
        )

    model_id, model_slot = _walk_passthrough(
        graph,
        sampler["inputs"].get("model"),
        "primary_model",
        frozenset(MODEL_LOADER_INPUTS),
        {"ModelSamplingAuraFlow": "model"},
    )
    positive_id, _ = _walk_passthrough(
        graph,
        sampler["inputs"].get("positive"),
        "positive_prompt",
        frozenset({"CLIPTextEncode"}),
        {},
    )
    negative_id, _ = _walk_passthrough(
        graph,
        sampler["inputs"].get("negative"),
        "negative_prompt",
        frozenset({"CLIPTextEncode"}),
        {"ConditioningZeroOut": "conditioning"},
    )
    if positive_id == negative_id:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Positive and negative prompts must be distinct.",
            {"role": "conditioning", "candidate_node_ids": [positive_id]},
        )

    model_class = str(_node(graph, model_id)["class_type"])
    if model_slot != 0:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Primary model path uses an unsupported loader output.",
            {"role": "primary_model", "candidate_node_ids": [model_id]},
        )
    topology = (
        "single_checkpoint" if model_class == "CheckpointLoaderSimple" else "split_model"
    )
    binding = {
        "model": [model_id, "inputs", MODEL_LOADER_INPUTS[model_class]],
        "positive_prompt": [positive_id, "inputs", "text"],
        "negative_prompt": [negative_id, "inputs", "text"],
        "seed": [sampler_id, "inputs", "seed"],
        "steps": [sampler_id, "inputs", "steps"],
        "guidance_scale": [sampler_id, "inputs", "cfg"],
        "sampler": [sampler_id, "inputs", "sampler_name"],
        "scheduler": [sampler_id, "inputs", "scheduler"],
        "width": [latent_id, "inputs", "width"],
        "height": [latent_id, "inputs", "height"],
        "output": [output_id],
    }
    try:
        components = workflow_component_bindings(graph)
    except ValidationError as error:
        raise ValidationError(
            "unsupported_workflow_topology",
            "Workflow loader topology is incomplete, mixed, or ambiguous.",
            {"details": getattr(error, "details", {})},
        ) from error
    expected_roles = (
        {"primary_model"}
        if topology == "single_checkpoint"
        else {"primary_model", "text_encoder", "vae"}
    )
    actual_roles = {item["role"] for item in components}
    if actual_roles != expected_roles:
        raise ValidationError(
            "unsupported_workflow_topology",
            "Workflow loader topology is incomplete, mixed, or ambiguous.",
            {"roles": sorted(actual_roles), "topology": topology},
        )

    _validate_component_edges(
        graph,
        topology,
        model_id,
        positive_id,
        negative_id,
        decoder_id,
    )
    return {
        "topology": topology,
        "binding": binding,
        "output_node": output_id,
        "components": components,
    }


def _validate_component_edges(
    graph: dict[str, object],
    topology: str,
    model_id: str,
    positive_id: str,
    negative_id: str,
    decoder_id: str,
) -> None:
    positive_clip = _link(
        _node(graph, positive_id)["inputs"].get("clip"),
        "positive_clip",
    )
    negative_clip = _link(
        _node(graph, negative_id)["inputs"].get("clip"),
        "negative_clip",
    )
    decoder_vae = _link(
        _node(graph, decoder_id)["inputs"].get("vae"),
        "decoder_vae",
    )
    if topology == "single_checkpoint":
        expected_clip = (model_id, 1)
        expected_vae = (model_id, 2)
    else:
        clip_id, _ = _only_class(graph, frozenset({"CLIPLoader"}), "text_encoder")
        vae_id, _ = _only_class(graph, frozenset({"VAELoader"}), "vae")
        expected_clip = (clip_id, 0)
        expected_vae = (vae_id, 0)
    failures = []
    if positive_clip != expected_clip:
        failures.append(positive_clip[0])
    if negative_clip != expected_clip:
        failures.append(negative_clip[0])
    if decoder_vae != expected_vae:
        failures.append(decoder_vae[0])
    if failures:
        raise ValidationError(
            "ambiguous_workflow_binding",
            "Conditioning or decoder components are disconnected or cross-wired.",
            {"role": "component_path", "candidate_node_ids": sorted(set(failures))},
        )
