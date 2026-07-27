from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from pathlib import Path

from .errors import ConflictError, ValidationError
from .model_identity import identity_token, validate_discovery_record
from .workflow_templates import (
    MODEL_LOADER_INPUTS,
    WorkflowTemplateRegistry,
    _canonical_hash,
    read_workflow_source,
    workflow_component_bindings,
)


PROPOSAL_SCHEMA_VERSION = 1
PROPOSAL_FIELDS = (
    "source_sha256", "workflow_sha256", "topology", "binding", "owned_output", "components",
)
EXCLUDED_CLASSES = frozenset((
    "VAEEncode", "VAEEncodeForInpaint", "LoadImage", "LoadImageMask",
    "ConditioningSetAreaPercentage", "ConditioningCombine", "SolidMask", "MaskComposite",
    "FeatherMask", "ImageCompositeMasked", "MaskToImage",
))


def _hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _reject(
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> None:
    raise ValidationError(code, message) if details is None else ValidationError(code, message, details)


def _looks_like_api_graph(value: object) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(node_id, str) and isinstance(node, dict)
            and isinstance(node.get("class_type"), str) and isinstance(node.get("inputs"), dict)
            for node_id, node in value.items()
        )
    )


def _extract_graph(value: object) -> dict[str, object]:
    if _looks_like_api_graph(value):
        return copy.deepcopy(value)
    if isinstance(value, dict) and _looks_like_api_graph(value.get("prompt")):
        other_graph_keys = sorted(key for key, item in value.items() if key != "prompt" and _looks_like_api_graph(item))
        if other_graph_keys:
            _reject("unsupported_workflow_envelope", "Workflow wrapper contains multiple API graph candidates.", {"fields": ["prompt", *other_graph_keys]})
        return copy.deepcopy(value["prompt"])
    if isinstance(value, dict) and {"nodes", "links"} <= set(value):
        _reject("unsupported_workflow_envelope", "ComfyUI UI format is unsupported; enable developer mode and export API format.")
    _reject(
        "unsupported_workflow_envelope",
        "Workflow must be a bare API graph or contain one API graph under prompt.",
    )


class WorkflowOnboarding:
    def __init__(
        self, workflows: WorkflowTemplateRegistry,
        inventory_provider: Callable[[], list[dict[str, object]]],
    ) -> None:
        if not isinstance(workflows, WorkflowTemplateRegistry) or not callable(
            inventory_provider
        ):
            _reject(
                "invalid_workflow_onboarding",
                "Workflow onboarding dependencies are invalid.",
            )
        self.workflows = workflows
        self.inventory_provider = inventory_provider

    def _prepare_source(
        self,
        path: Path,
    ) -> tuple[bytes, dict[str, object], dict[str, object]]:
        encoded, source_value = read_workflow_source(Path(path))
        graph = _extract_graph(source_value)
        inferred = infer_workflow_binding(graph)
        prepared = self.workflows.prepare_import(
            graph,
            inferred["binding"],
            _component_model_names(inferred["components"]),
        )
        if prepared["operation"] != "txt2img":
            _reject(
                "unsupported_workflow_operation",
                "Workflow onboarding supports ordinary txt2img only.",
            )
        return encoded, inferred, prepared

    def prepare_trust_binding(
        self,
        path: Path,
        binding: object,
    ) -> dict[str, object]:
        _encoded, inferred, prepared = self._prepare_source(Path(path))
        if binding != inferred["binding"]:
            _reject(
                "invalid_workflow_binding",
                "Workflow trust binding differs from the current inferred binding.",
            )
        _matched, failures = self._match_inventory(inferred["components"])
        if failures:
            _reject(
                "workflow_model_binding_ambiguous",
                "Workflow trust preparation requires exact current component identities.",
                {"inventory_diagnostics": failures},
            )
        return prepared

    def inspect(self, path: Path) -> dict[str, object]:
        encoded, inferred, prepared = self._prepare_source(Path(path))
        source_sha256 = hashlib.sha256(encoded).hexdigest()
        matched, match_failures = self._match_inventory(inferred["components"])
        result: dict[str, object] = {
            "status": "registerable" if not match_failures else "diagnostic",
            "registrable": not match_failures,
            "source_sha256": source_sha256,
            "workflow_sha256": prepared["workflow_sha256"],
            "topology": inferred["topology"],
            "binding": inferred["binding"],
            "owned_output": {"node_id": inferred["output_node"]},
            "components": matched,
            "limitations": [
                "ordinary_txt2img_only", "no_custom_nodes_or_graph_editing",
                "registration_does_not_grant_model_trust_or_public_authority",
            ],
            "recoverable_next_actions": (
                ["local_gpu_register_workflow"] if not match_failures
                else ["local_gpu_discover_models"]
            ),
        }
        if not match_failures:
            proposal = {
                "schema_version": PROPOSAL_SCHEMA_VERSION,
                **{key: result[key] for key in PROPOSAL_FIELDS},
            }
            digest = _canonical_hash(proposal)
            result["proposal_digest"] = digest
            result["confirmation"] = f"register_workflow:{source_sha256}:{digest}"
        else:
            result["inventory_diagnostics"] = match_failures
        return result

    def register(
        self, path: Path, proposal_digest: str, confirmation: str,
    ) -> dict[str, object]:
        if not _hex64(proposal_digest):
            _reject("invalid_workflow_confirmation", "Workflow proposal digest must be 64 lowercase hex characters.")
        current = self.inspect(Path(path))
        if not current["registrable"]:
            raise ConflictError(
                "workflow_proposal_stale",
                "Workflow or current inventory no longer matches a registerable proposal.",
            )
        if proposal_digest != current["proposal_digest"]:
            raise ConflictError(
                "workflow_proposal_stale",
                "Workflow proposal changed after inspection.",
            )
        if confirmation != current["confirmation"]:
            _reject(
                "invalid_workflow_confirmation",
                "Workflow registration confirmation does not match exact current bytes and proposal.",
            )

        encoded, source_value = read_workflow_source(Path(path))
        if hashlib.sha256(encoded).hexdigest() != current["source_sha256"]:
            raise ConflictError(
                "workflow_proposal_stale",
                "Workflow source bytes changed during registration revalidation.",
            )
        graph = _extract_graph(source_value)
        prepared = self.workflows.prepare_import(graph, current["binding"], _component_model_names(current["components"]))
        if prepared["workflow_sha256"] != current["workflow_sha256"]:
            raise ConflictError(
                "workflow_proposal_stale",
                "Workflow changed during registration revalidation.",
            )
        stored = self.workflows.store_prepared_import(prepared)
        return {
            "registered_workflow_id": stored["template_id"],
            "template_version": stored["template_version"],
            **{key: current[key] for key in ("source_sha256", "topology", "owned_output", "components")},
            "workflow_sha256": stored["workflow_sha256"],
            "recoverable_next_actions": ["local_gpu_set_model_trust"],
        }

    def _match_inventory(
        self, components: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
        raw_inventory = self.inventory_provider()
        inventory: list[dict[str, object]] = []
        for value in raw_inventory if isinstance(raw_inventory, list) else []:
            try:
                inventory.append(validate_discovery_record(value))
            except ValidationError:
                continue

        matched: list[dict[str, str]] = []
        failures: list[dict[str, object]] = []
        endpoints: set[str] = set()
        for component in components:
            candidates = []
            for record in inventory:
                metadata = record.get("metadata")
                if _inventory_match(record, metadata, component):
                    candidates.append(record)
            public_component = copy.deepcopy(component)
            if len(candidates) == 1:
                record = candidates[0]
                public_component["identity_token"] = identity_token(record)
                endpoints.add(str(record["endpoint_identity"]))
            else:
                failures.append({
                    "role": component["role"], "candidate_count": len(candidates),
                    "reason": "unavailable" if not candidates else "ambiguous",
                })
            matched.append(public_component)
        if len(endpoints) > 1:
            failures.append({
                "role": "workflow", "reason": "endpoint_mismatch",
                "candidate_count": len(endpoints),
            })
        return matched, failures

def _inventory_match(record: dict[str, object], metadata: object, component: dict[str, str]) -> bool:
    return (
        record.get("backend") == "comfyui"
        and record.get("backend_model_id") == component["backend_model_id"]
        and isinstance(metadata, dict)
        and metadata.get("loader_class") == component["loader_class"]
        and metadata.get("loader_input") == component["loader_input"]
    )


def _component_model_names(components: object) -> list[str]:
    return [item["backend_model_id"] for item in components if isinstance(item, dict)]


def _node(graph: dict[str, object], node_id: str) -> dict[str, object]:
    value = graph.get(node_id)
    if not isinstance(value, dict) or not isinstance(value.get("inputs"), dict):
        _reject(
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
        _reject(
            "ambiguous_workflow_binding",
            f"Workflow {role} is not one exact graph edge.",
            {"role": role, "candidate_node_ids": []},
        )
    return value[0], value[1]


def _only_class(graph: dict[str, object], classes: frozenset[str], role: str) -> tuple[str, dict[str, object]]:
    matches = sorted(
        (node_id, node)
        for node_id, node in graph.items()
        if isinstance(node, dict) and node.get("class_type") in classes
    )
    if len(matches) != 1:
        _reject(
            "ambiguous_workflow_binding",
            f"Workflow requires one unambiguous {role}.",
            {"role": role, "candidate_node_ids": [item[0] for item in matches]},
        )
    return matches[0]


def _walk_passthrough(
    graph: dict[str, object], edge: object, role: str,
    targets: frozenset[str], passthrough_input: dict[str, str],
) -> tuple[str, int]:
    seen: set[str] = set()
    node_id, slot = _link(edge, role)
    while True:
        if node_id in seen:
            _reject(
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
            _reject(
                "ambiguous_workflow_binding",
                f"Workflow {role} does not reach one reviewed source.",
                {"role": role, "candidate_node_ids": [node_id]},
            )
        node_id, slot = _link(node["inputs"].get(input_name), role)


def infer_workflow_binding(graph: object) -> dict[str, object]:
    if not isinstance(graph, dict) or not graph:
        _reject(
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
        _reject(
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
        _reject(
            "ambiguous_workflow_binding",
            "Sampler latent path is cross-wired.",
        )
    if _link(decoder["inputs"].get("samples"), "decoder")[0] != sampler_id:
        _reject(
            "ambiguous_workflow_binding",
            "Decoder sample path is cross-wired.",
        )
    if _link(output["inputs"].get("images"), "owned_output")[0] != decoder_id:
        _reject(
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
        _reject(
            "ambiguous_workflow_binding",
            "Positive and negative prompts must be distinct.",
            {"role": "conditioning", "candidate_node_ids": [positive_id]},
        )

    model_class = str(_node(graph, model_id)["class_type"])
    if model_slot != 0:
        _reject(
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
        _reject(
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
    graph: dict[str, object], topology: str, model_id: str,
    positive_id: str, negative_id: str, decoder_id: str,
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
        _reject(
            "ambiguous_workflow_binding",
            "Conditioning or decoder components are disconnected or cross-wired.",
            {"role": "component_path", "candidate_node_ids": sorted(set(failures))},
        )
