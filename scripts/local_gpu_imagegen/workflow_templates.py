from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Collection
from pathlib import Path, PurePosixPath, PureWindowsPath

from .artifacts import atomic_write_json
from .errors import ArtifactError, ConflictError, ValidationError
from .regional_layout import (
    LAYOUT_MODE,
    REGIONAL_TEMPLATE_ID,
    validate_regional_conditioning,
    validate_regional_layout,
)
from .two_stage_layout import (
    TWO_STAGE_LAYOUT_MODE,
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
    derive_subject_seed,
    validate_two_stage_conditioning,
    validate_two_stage_layout,
)


SAFE_NODE_INPUTS = {
    "CheckpointLoaderSimple": frozenset({"ckpt_name"}),
    "UNETLoader": frozenset({"unet_name", "weight_dtype"}),
    "CLIPLoader": frozenset({"clip_name", "type", "device"}),
    "VAELoader": frozenset({"vae_name"}),
    "CLIPTextEncode": frozenset({"text", "clip"}),
    "ConditioningZeroOut": frozenset({"conditioning"}),
    "EmptyLatentImage": frozenset({"width", "height", "batch_size"}),
    "EmptySD3LatentImage": frozenset({"width", "height", "batch_size"}),
    "ModelSamplingAuraFlow": frozenset({"model", "shift"}),
    "KSampler": frozenset({
        "seed",
        "steps",
        "cfg",
        "sampler_name",
        "scheduler",
        "denoise",
        "model",
        "positive",
        "negative",
        "latent_image",
    }),
    "VAEDecode": frozenset({"samples", "vae"}),
    "VAEEncode": frozenset({"pixels", "vae"}),
    "VAEEncodeForInpaint": frozenset({"pixels", "vae", "mask", "grow_mask_by"}),
    "LoadImage": frozenset({"image"}),
    "LoadImageMask": frozenset({"image", "channel"}),
    "SaveImage": frozenset({"filename_prefix", "images"}),
}
SAFE_NODE_CLASSES = frozenset(SAFE_NODE_INPUTS)
REGIONAL_NODE_INPUTS = {
    "ConditioningSetAreaPercentage": frozenset({
        "conditioning",
        "width",
        "height",
        "x",
        "y",
        "strength",
    }),
    "ConditioningCombine": frozenset({"conditioning_1", "conditioning_2"}),
}
REGIONAL_NODE_CLASSES = frozenset(REGIONAL_NODE_INPUTS)
SHIPPED_REGIONAL_NODE_INPUTS = {**SAFE_NODE_INPUTS, **REGIONAL_NODE_INPUTS}
TWO_STAGE_NODE_INPUTS = {
    "SolidMask": frozenset({"value", "width", "height"}),
    "MaskComposite": frozenset({"destination", "source", "x", "y", "operation"}),
    "FeatherMask": frozenset({"mask", "left", "top", "right", "bottom"}),
    "ImageCompositeMasked": frozenset({
        "destination", "source", "x", "y", "resize_source", "mask",
    }),
    "MaskToImage": frozenset({"mask"}),
}
SHIPPED_TWO_STAGE_NODE_INPUTS = {**SAFE_NODE_INPUTS, **TWO_STAGE_NODE_INPUTS}
MODEL_LOADER_INPUTS = {
    "CheckpointLoaderSimple": "ckpt_name",
    "UNETLoader": "unet_name",
}
COMPONENT_LOADER_INPUTS = {
    **MODEL_LOADER_INPUTS,
    "CLIPLoader": "clip_name",
    "VAELoader": "vae_name",
}
COMPONENT_LOADER_ROLES = {
    "CheckpointLoaderSimple": "primary_model",
    "UNETLoader": "primary_model",
    "CLIPLoader": "text_encoder",
    "VAELoader": "vae",
}
FORBIDDEN_TERMS = (
    "shell",
    "python",
    "script",
    "process",
    "download",
    "http",
    "webhook",
    "fetch",
    "execute",
    "command",
)
REQUIRED_BINDINGS = frozenset({
    "model",
    "positive_prompt",
    "negative_prompt",
    "seed",
    "steps",
    "guidance_scale",
    "sampler",
    "scheduler",
    "width",
    "height",
    "output",
})
PARAMETER_KEYS = REQUIRED_BINDINGS - {"model", "output"}
REGIONAL_BINDING_KEYS = frozenset({
    "copy_prompt",
    "copy_x",
    "copy_y",
    "copy_width",
    "copy_height",
    "copy_strength",
    "subject_prompt",
    "subject_x",
    "subject_y",
    "subject_width",
    "subject_height",
    "subject_strength",
})
OPERATIONS = frozenset({"txt2img", "img2img", "inpaint"})
MAX_NODES = 64
MAX_STEPS = 80
MIN_DIMENSION = 256
MAX_DIMENSION = 1536
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SEED = 2**64 - 1
TEMPLATE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
IMPORTED_ID_PATTERN = re.compile(r"^imported:([0-9a-f]{64})$")

TWO_STAGE_OUTPUT_NODES = {"base": "19", "mask": "20", "final": "21"}
TWO_STAGE_BINDINGS = {
    "model": ["1", "inputs", "ckpt_name"],
    "positive_prompt": ["3", "inputs", "text"],
    "negative_prompt": ["4", "inputs", "text"],
    "seed": ["5", "inputs", "seed"],
    "steps": ["5", "inputs", "steps"],
    "guidance_scale": ["5", "inputs", "cfg"],
    "sampler": ["5", "inputs", "sampler_name"],
    "scheduler": ["5", "inputs", "scheduler"],
    "width": ["2", "inputs", "width"],
    "height": ["2", "inputs", "height"],
}
TWO_STAGE_NODE_CLASSES = {
    "1": "CheckpointLoaderSimple",
    "2": "EmptyLatentImage",
    "3": "CLIPTextEncode",
    "4": "CLIPTextEncode",
    "5": "KSampler",
    "6": "VAEDecode",
    "7": "CLIPTextEncode",
    "8": "CLIPTextEncode",
    "9": "SolidMask",
    "10": "SolidMask",
    "11": "MaskComposite",
    "12": "FeatherMask",
    "13": "MaskComposite",
    "14": "VAEEncodeForInpaint",
    "15": "KSampler",
    "16": "VAEDecode",
    "17": "ImageCompositeMasked",
    "18": "MaskToImage",
    "19": "SaveImage",
    "20": "SaveImage",
    "21": "SaveImage",
}
TWO_STAGE_EDGES = {
    ("3", "clip"): ["1", 1],
    ("4", "clip"): ["1", 1],
    ("5", "model"): ["1", 0],
    ("5", "positive"): ["3", 0],
    ("5", "negative"): ["4", 0],
    ("5", "latent_image"): ["2", 0],
    ("6", "samples"): ["5", 0],
    ("6", "vae"): ["1", 2],
    ("7", "clip"): ["1", 1],
    ("8", "clip"): ["1", 1],
    ("11", "destination"): ["9", 0],
    ("11", "source"): ["10", 0],
    ("12", "mask"): ["10", 0],
    ("13", "destination"): ["9", 0],
    ("13", "source"): ["12", 0],
    ("14", "pixels"): ["6", 0],
    ("14", "vae"): ["1", 2],
    ("14", "mask"): ["11", 0],
    ("15", "model"): ["1", 0],
    ("15", "positive"): ["7", 0],
    ("15", "negative"): ["8", 0],
    ("15", "latent_image"): ["14", 0],
    ("16", "samples"): ["15", 0],
    ("16", "vae"): ["1", 2],
    ("17", "destination"): ["6", 0],
    ("17", "source"): ["16", 0],
    ("17", "mask"): ["13", 0],
    ("18", "mask"): ["13", 0],
    ("19", "images"): ["6", 0],
    ("20", "images"): ["18", 0],
    ("21", "images"): ["17", 0],
}
TWO_STAGE_TEMPLATE_SCALARS = {
    ("1", "ckpt_name"): "sd_xl_base_1.0.safetensors",
    ("2", "width"): 1280,
    ("2", "height"): 720,
    ("2", "batch_size"): 1,
    ("3", "text"): "",
    ("4", "text"): "",
    ("5", "seed"): 0,
    ("5", "steps"): 30,
    ("5", "cfg"): 7.0,
    ("5", "sampler_name"): "dpmpp_2m",
    ("5", "scheduler"): "karras",
    ("5", "denoise"): 1.0,
    ("7", "text"): "",
    ("8", "text"): "",
    ("9", "value"): 0.0,
    ("9", "width"): 1280,
    ("9", "height"): 720,
    ("10", "value"): 1.0,
    ("10", "width"): 512,
    ("10", "height"): 672,
    ("11", "x"): 720,
    ("11", "y"): 24,
    ("11", "operation"): "add",
    ("12", "left"): 32,
    ("12", "top"): 32,
    ("12", "right"): 32,
    ("12", "bottom"): 32,
    ("13", "x"): 720,
    ("13", "y"): 24,
    ("13", "operation"): "add",
    ("14", "grow_mask_by"): 8,
    ("15", "seed"): 1,
    ("15", "steps"): 30,
    ("15", "cfg"): 7.0,
    ("15", "sampler_name"): "dpmpp_2m",
    ("15", "scheduler"): "karras",
    ("15", "denoise"): 0.9,
    ("17", "x"): 0,
    ("17", "y"): 0,
    ("17", "resize_source"): False,
    ("19", "filename_prefix"): "local-gpu-imagegen",
    ("20", "filename_prefix"): "local-gpu-imagegen",
    ("21", "filename_prefix"): "local-gpu-imagegen",
}


class WorkflowTemplateRegistry:
    def __init__(self, repository_root: Path, state_dir: Path) -> None:
        self.repository_root = Path(repository_root)
        self.state_dir = Path(state_dir)
        self.registered_root = self.state_dir / "workflows"

    def resolve(
        self,
        template_id: str,
        model_id: str,
        operation: str,
        parameters: dict[str, object],
        *,
        regional_layout: object = None,
        regional_conditioning: object = None,
        two_stage_layout: object = None,
        two_stage_conditioning: object = None,
    ) -> dict[str, object]:
        if not isinstance(template_id, str):
            raise ValidationError(
                "invalid_workflow_template",
                "Workflow template ID must be a string.",
            )
        if template_id.startswith("imported:"):
            template = self.load_registered(template_id)
        else:
            template = self._load_shipped(template_id)
        graph, normalized_model = self._render_standard_bindings(
            template,
            model_id,
            operation,
            parameters,
        )
        layout_mode = template.get("layout_mode")
        if layout_mode is None:
            if any(value is not None for value in (
                regional_layout,
                regional_conditioning,
                two_stage_layout,
                two_stage_conditioning,
            )):
                raise ValidationError(
                    "invalid_regional_conditioning",
                    "Standard workflows reject layout conditioning data.",
                )
        elif layout_mode == LAYOUT_MODE:
            if two_stage_layout is not None or two_stage_conditioning is not None:
                raise ValidationError(
                    "invalid_two_stage_conditioning",
                    "Regional workflows reject two-stage data.",
                )
            layout = validate_regional_layout(regional_layout)
            conditioning = validate_regional_conditioning(regional_conditioning)
            _bind_regional_values(
                graph,
                template["regional_bindings"],
                layout,
                conditioning,
            )
        elif layout_mode == TWO_STAGE_LAYOUT_MODE:
            if regional_layout is not None or regional_conditioning is not None:
                raise ValidationError(
                    "invalid_regional_conditioning",
                    "Two-stage workflows reject regional data.",
                )
            layout = validate_two_stage_layout(two_stage_layout)
            conditioning = validate_two_stage_conditioning(two_stage_conditioning)
            canvas = layout["canvas"]
            if (
                parameters.get("width") != canvas["width"]
                or parameters.get("height") != canvas["height"]
            ):
                raise ValidationError(
                    "invalid_workflow_parameters",
                    "Two-stage parameters must match the confirmed canvas.",
                )
            _bind_two_stage_values(graph, parameters, layout, conditioning)
        else:
            raise ArtifactError(
                "invalid_workflow_template",
                "Reviewed layout mode is unsupported.",
            )
        self._validate_rendered(
            template,
            graph,
            normalized_model,
            two_stage_layout=layout if layout_mode == TWO_STAGE_LAYOUT_MODE else None,
        )
        return _rendered_result(
            template,
            graph,
            two_stage_layout=layout if layout_mode == TWO_STAGE_LAYOUT_MODE else None,
        )

    def inspect_shipped(
        self,
        template_id: str,
        model_id: str,
        operation: str,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        template = self._load_shipped(template_id)
        graph, normalized_model = self._render_standard_bindings(
            template,
            model_id,
            operation,
            parameters,
        )
        self._validate_rendered(template, graph, normalized_model)
        return _rendered_result(template, graph)

    @staticmethod
    def _render_standard_bindings(
        template: dict[str, object],
        model_id: str,
        operation: str,
        parameters: dict[str, object],
    ) -> tuple[dict[str, object], str]:
        if operation != template["operation"]:
            raise ValidationError(
                "unsupported_workflow_operation",
                "Workflow template does not support the requested operation.",
            )
        normalized_parameters = _validate_parameters(parameters)
        normalized_model = _validate_model_name(model_id)
        graph = copy.deepcopy(template["graph"])
        bindings = template["bindings"]
        _set_binding(graph, bindings["model"], normalized_model)
        for key, value in normalized_parameters.items():
            _set_binding(graph, bindings[key], value)
        return graph, normalized_model

    @staticmethod
    def _validate_rendered(
        template: dict[str, object],
        graph: dict[str, object],
        normalized_model: str,
        *,
        two_stage_layout: object = None,
    ) -> None:
        if template.get("layout_mode") == TWO_STAGE_LAYOUT_MODE:
            _validate_rendered_two_stage_workflow(
                graph,
                normalized_model,
                two_stage_layout=two_stage_layout,
            )
            return
        validator = (
            _validate_reviewed_regional_workflow
            if template.get("layout_mode") == LAYOUT_MODE
            else validate_imported_workflow
        )
        validator(
            graph,
            {**template["bindings"], "output": [template["output_node"]]},
            [normalized_model],
        )

    def register_import(
        self,
        path: Path,
        binding: object,
        available_models: Collection[str],
    ) -> dict[str, object]:
        source = Path(path)
        graph = _read_source_graph(source)
        _freeze_single_import_model(graph, binding, available_models)
        normalized = validate_imported_workflow(graph, binding, available_models)
        operation = _infer_operation(normalized["graph"])
        payload = {
            "operation": operation,
            "model_families": ["unknown"],
            "bindings": {
                key: value
                for key, value in normalized["binding"].items()
                if key != "output"
            },
            "output_node": normalized["output_node"],
            "graph": normalized["graph"],
        }
        digest = _canonical_hash(payload)
        document: dict[str, object] = {
            "schema_version": 1,
            "template_id": f"imported:{digest}",
            "template_version": 1,
            "workflow_sha256": digest,
            **payload,
        }
        if self.registered_root.exists() and _link_like(self.registered_root):
            raise ArtifactError(
                "invalid_workflow_state",
                "Workflow state directory must not be a link or reparse point.",
            )
        target = self.registered_root / f"{digest}.json"
        atomic_write_json(target, document)
        return {**copy.deepcopy(document), "local_path": str(target.absolute())}

    def load_registered(self, template_id: str) -> dict[str, object]:
        match = IMPORTED_ID_PATTERN.fullmatch(template_id) if isinstance(template_id, str) else None
        if match is None:
            raise ValidationError(
                "invalid_workflow_template",
                "Imported workflow template ID is invalid.",
            )
        digest = match.group(1)
        path = self.registered_root / f"{digest}.json"
        try:
            document = _read_bounded_json(path)
            normalized = _validate_registered_document(document, digest)
        except (ArtifactError, ValidationError, KeyError, TypeError, ValueError) as error:
            raise ConflictError(
                "workflow_registration_drifted",
                "Registered workflow copy changed or became unreadable.",
            ) from error
        return {**normalized, "local_path": str(path.absolute())}

    def _load_shipped(self, template_id: str) -> dict[str, object]:
        if TEMPLATE_ID_PATTERN.fullmatch(template_id) is None:
            raise ValidationError(
                "invalid_workflow_template",
                "Workflow template ID is invalid.",
            )
        matches: list[dict[str, object]] = []
        try:
            paths = sorted(self.repository_root.glob("*.json"))
        except OSError as error:
            raise ArtifactError(
                "invalid_workflow_template",
                "Workflow template directory is unreadable.",
            ) from error
        for path in paths:
            document = _read_bounded_json(path)
            if isinstance(document, dict) and document.get("template_id") == template_id:
                matches.append(_validate_shipped_document(document))
        if len(matches) != 1:
            raise ValidationError(
                "workflow_template_not_found",
                "Exactly one reviewed workflow template must match the requested ID.",
            )
        return matches[0]


def _rendered_result(
    template: dict[str, object],
    graph: dict[str, object],
    *,
    two_stage_layout: object = None,
) -> dict[str, object]:
    families = template["model_families"]
    model_family = "sd15" if "sd15" in families else families[0]
    result = {
        "template_id": template["template_id"],
        "template_version": template["template_version"],
        "workflow_sha256": template["workflow_sha256"],
        "operation": template["operation"],
        "model_family": model_family,
        "graph": graph,
    }
    if template.get("layout_mode") == TWO_STAGE_LAYOUT_MODE:
        result["output_nodes"] = copy.deepcopy(template["output_nodes"])
        if two_stage_layout is not None:
            result["control_sha256"] = build_control_identity(
                two_stage_layout,
                template["workflow_sha256"],
                template["stage_contract"],
            )
    else:
        result["output_node"] = template["output_node"]
    if template.get("layout_mode") is not None:
        result["layout_mode"] = template["layout_mode"]
    return result


def _bind_regional_values(
    graph: dict[str, object],
    bindings: dict[str, list[str]],
    layout: dict[str, object],
    conditioning: dict[str, object],
) -> None:
    copy_region = layout["copy_region"]
    subject_region = layout["subject_region"]
    values = {
        "copy_prompt": conditioning["copy_prompt"],
        "copy_x": copy_region["x"],
        "copy_y": copy_region["y"],
        "copy_width": copy_region["width"],
        "copy_height": copy_region["height"],
        "copy_strength": conditioning["copy_strength"],
        "subject_prompt": conditioning["subject_prompt"],
        "subject_x": subject_region["x"],
        "subject_y": subject_region["y"],
        "subject_width": subject_region["width"],
        "subject_height": subject_region["height"],
        "subject_strength": conditioning["subject_strength"],
    }
    for key, value in values.items():
        _set_binding(graph, bindings[key], value)


def _bind_two_stage_values(
    graph: dict[str, object],
    parameters: dict[str, object],
    layout: dict[str, object],
    conditioning: dict[str, object],
) -> None:
    canvas = layout["canvas"]
    subject = layout["subject_mask_rect"]
    graph["2"]["inputs"].update(width=canvas["width"], height=canvas["height"])
    graph["9"]["inputs"].update(width=canvas["width"], height=canvas["height"])
    graph["10"]["inputs"].update(width=subject["width"], height=subject["height"])
    for node_id in ("11", "13"):
        graph[node_id]["inputs"].update(x=subject["x"], y=subject["y"])
    graph["12"]["inputs"].update(
        left=layout["feather_pixels"],
        top=layout["feather_pixels"],
        right=layout["feather_pixels"],
        bottom=layout["feather_pixels"],
    )
    graph["14"]["inputs"]["grow_mask_by"] = layout["vae_grow_mask_by"]
    graph["7"]["inputs"]["text"] = conditioning["subject_prompt"]
    graph["8"]["inputs"]["text"] = conditioning["subject_negative_prompt"]
    graph["15"]["inputs"]["seed"] = derive_subject_seed(parameters["seed"])
    for field, parameter in (
        ("steps", "steps"),
        ("cfg", "guidance_scale"),
        ("sampler_name", "sampler"),
        ("scheduler", "scheduler"),
    ):
        graph["15"]["inputs"][field] = copy.deepcopy(parameters[parameter])
    graph["5"]["inputs"]["denoise"] = 1.0
    graph["15"]["inputs"]["denoise"] = conditioning["subject_denoise"]


def _validate_regional_bindings(
    value: object,
    graph: dict[str, object],
    standard_bindings: dict[str, list[str]],
) -> dict[str, list[str]]:
    if not isinstance(value, dict) or set(value) != REGIONAL_BINDING_KEYS:
        raise _unsafe("Regional workflow bindings are incomplete or unexpected.")
    expected_inputs = {
        "copy_prompt": ("CLIPTextEncode", "text"),
        "copy_x": ("ConditioningSetAreaPercentage", "x"),
        "copy_y": ("ConditioningSetAreaPercentage", "y"),
        "copy_width": ("ConditioningSetAreaPercentage", "width"),
        "copy_height": ("ConditioningSetAreaPercentage", "height"),
        "copy_strength": ("ConditioningSetAreaPercentage", "strength"),
        "subject_prompt": ("CLIPTextEncode", "text"),
        "subject_x": ("ConditioningSetAreaPercentage", "x"),
        "subject_y": ("ConditioningSetAreaPercentage", "y"),
        "subject_width": ("ConditioningSetAreaPercentage", "width"),
        "subject_height": ("ConditioningSetAreaPercentage", "height"),
        "subject_strength": ("ConditioningSetAreaPercentage", "strength"),
    }
    targets = {tuple(path) for path in standard_bindings.values()}
    normalized: dict[str, list[str]] = {}
    for key, path in value.items():
        if (
            not isinstance(path, list)
            or len(path) != 3
            or any(not isinstance(item, str) or not item for item in path)
            or tuple(path) in targets
        ):
            raise _unsafe("Regional workflow binding paths are invalid.")
        node = graph.get(path[0])
        expected_class, expected_input = expected_inputs[key]
        if (
            path[1] != "inputs"
            or path[2] != expected_input
            or not isinstance(node, dict)
            or node.get("class_type") != expected_class
            or not isinstance(node.get("inputs"), dict)
            or path[2] not in node["inputs"]
            or isinstance(node["inputs"][path[2]], (dict, list))
        ):
            raise _unsafe("Regional workflow binding targets the wrong scalar input.")
        targets.add(tuple(path))
        normalized[key] = list(path)

    copy_area = {
        normalized[key][0]
        for key in normalized
        if key.startswith("copy_") and key != "copy_prompt"
    }
    subject_area = {
        normalized[key][0]
        for key in normalized
        if key.startswith("subject_") and key != "subject_prompt"
    }
    copy_prompt_node = normalized["copy_prompt"][0]
    subject_prompt_node = normalized["subject_prompt"][0]
    if (
        len(copy_area) != 1
        or len(subject_area) != 1
        or copy_area == subject_area
        or copy_prompt_node == subject_prompt_node
    ):
        raise _unsafe("Regional workflow zones must bind distinct reviewed nodes.")
    copy_area_node = graph[next(iter(copy_area))]
    subject_area_node = graph[next(iter(subject_area))]
    if (
        copy_area_node["inputs"].get("conditioning") != [copy_prompt_node, 0]
        or subject_area_node["inputs"].get("conditioning")
        != [subject_prompt_node, 0]
    ):
        raise _unsafe("Regional workflow prompt and area edges are inconsistent.")
    return normalized


def _regional_layout_from_graph(
    graph: dict[str, object],
    bindings: dict[str, list[str]],
) -> dict[str, object]:
    def bound(key: str) -> object:
        path = bindings[key]
        return graph[path[0]][path[1]][path[2]]

    return {
        "mode": LAYOUT_MODE,
        "copy_region": {
            "x": bound("copy_x"),
            "y": bound("copy_y"),
            "width": bound("copy_width"),
            "height": bound("copy_height"),
        },
        "subject_region": {
            "x": bound("subject_x"),
            "y": bound("subject_y"),
            "width": bound("subject_width"),
            "height": bound("subject_height"),
        },
    }


def workflow_component_bindings(graph: object) -> list[dict[str, str]]:
    if not isinstance(graph, dict):
        raise ValidationError(
            "invalid_workflow_components",
            "Workflow graph must be an object before components can be bound.",
        )
    components: list[dict[str, str]] = []
    roles: set[str] = set()
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        loader_class = node.get("class_type")
        loader_input = COMPONENT_LOADER_INPUTS.get(loader_class)
        inputs = node.get("inputs")
        if loader_input is None or not isinstance(inputs, dict):
            continue
        backend_model_id = inputs.get(loader_input)
        role = COMPONENT_LOADER_ROLES[loader_class]
        if not isinstance(backend_model_id, str) or not backend_model_id:
            raise ValidationError(
                "invalid_workflow_components",
                "Workflow component loader has no frozen backend model name.",
            )
        if role in roles:
            raise ValidationError(
                "invalid_workflow_components",
                "Workflow component roles must be unique.",
            )
        roles.add(role)
        components.append({
            "role": role,
            "loader_class": loader_class,
            "loader_input": loader_input,
            "backend_model_id": backend_model_id,
        })
    if "primary_model" not in roles:
        raise ValidationError(
            "invalid_workflow_components",
            "Workflow must freeze one primary model component.",
        )
    components.sort(
        key=lambda item: (
            item["role"],
            item["loader_class"],
            item["loader_input"],
            item["backend_model_id"],
        )
    )
    return components


def validate_imported_workflow(
    graph: object,
    binding: object,
    available_models: Collection[str],
) -> dict[str, object]:
    return _validate_workflow(
        graph,
        binding,
        available_models,
        SAFE_NODE_INPUTS,
    )


def _validate_reviewed_regional_workflow(
    graph: object,
    binding: object,
    available_models: Collection[str],
) -> dict[str, object]:
    return _validate_workflow(
        graph,
        binding,
        available_models,
        SHIPPED_REGIONAL_NODE_INPUTS,
    )


def _validate_two_stage_graph(
    graph: object,
    available_models: Collection[str],
    *,
    template_scalars: bool,
) -> dict[str, object]:
    if not isinstance(graph, dict) or set(graph) != set(TWO_STAGE_NODE_CLASSES):
        raise _unsafe("Two-stage workflow must contain the exact reviewed node IDs.")
    normalized = copy.deepcopy(graph)
    for node_id, class_type in TWO_STAGE_NODE_CLASSES.items():
        node = normalized.get(node_id)
        if (
            not isinstance(node, dict)
            or set(node) != {"class_type", "inputs"}
            or node.get("class_type") != class_type
            or not isinstance(node.get("inputs"), dict)
            or set(node["inputs"]) != SHIPPED_TWO_STAGE_NODE_INPUTS[class_type]
        ):
            raise _unsafe("Two-stage workflow node contract drifted.", node_id)
    actual_edges = {
        (node_id, field): value
        for node_id, node in normalized.items()
        for field, value in node["inputs"].items()
        if isinstance(value, list)
    }
    if actual_edges != TWO_STAGE_EDGES:
        raise _unsafe("Two-stage workflow edges drifted.")
    if template_scalars:
        actual_scalars = {
            (node_id, field): value
            for node_id, node in normalized.items()
            for field, value in node["inputs"].items()
            if not isinstance(value, list)
        }
        if (
            set(actual_scalars) != set(TWO_STAGE_TEMPLATE_SCALARS)
            or any(
                not _same_typed_scalar(actual_scalars[key], expected)
                for key, expected in TWO_STAGE_TEMPLATE_SCALARS.items()
            )
        ):
            raise _unsafe("Two-stage workflow template scalars drifted.")
    _validate_edges(normalized)
    _enforce_resource_limits(normalized)
    model_names = {
        _validate_model_name(item)
        for item in available_models
        if isinstance(item, str)
    }
    if (
        isinstance(available_models, (str, bytes))
        or not isinstance(available_models, Collection)
        or len(model_names) != len(available_models)
    ):
        raise _unsafe("Available model names are invalid or duplicated.")
    _enforce_model_names(normalized, model_names)
    return normalized


def _validate_rendered_two_stage_workflow(
    graph: object,
    normalized_model: str,
    *,
    two_stage_layout: object = None,
) -> None:
    normalized = _validate_two_stage_graph(
        graph,
        [normalized_model],
        template_scalars=False,
    )
    inputs = {node_id: node["inputs"] for node_id, node in normalized.items()}
    static_values = {
        ("2", "batch_size"): 1,
        ("5", "denoise"): 1.0,
        ("9", "value"): 0.0,
        ("10", "value"): 1.0,
        ("11", "operation"): "add",
        ("13", "operation"): "add",
        ("17", "x"): 0,
        ("17", "y"): 0,
        ("17", "resize_source"): False,
        ("19", "filename_prefix"): "local-gpu-imagegen",
        ("20", "filename_prefix"): "local-gpu-imagegen",
        ("21", "filename_prefix"): "local-gpu-imagegen",
    }
    if any(
        not _same_typed_scalar(inputs[node_id][field], expected)
        for (node_id, field), expected in static_values.items()
    ):
        raise _unsafe("Two-stage workflow static values drifted.")
    if (
        inputs["9"]["width"] != inputs["2"]["width"]
        or inputs["9"]["height"] != inputs["2"]["height"]
        or inputs["11"]["x"] != inputs["13"]["x"]
        or inputs["11"]["y"] != inputs["13"]["y"]
        or len({
            inputs["12"][side]
            for side in ("left", "top", "right", "bottom")
        }) != 1
        or inputs["15"]["seed"] != derive_subject_seed(inputs["5"]["seed"])
        or any(
            inputs["15"][field] != inputs["5"][field]
            for field in ("steps", "cfg", "sampler_name", "scheduler")
        )
    ):
        raise _unsafe("Two-stage workflow bound values are inconsistent.")
    if two_stage_layout is not None:
        layout = validate_two_stage_layout(two_stage_layout)
        subject = layout["subject_mask_rect"]
        if (
            inputs["2"]["width"] != layout["canvas"]["width"]
            or inputs["2"]["height"] != layout["canvas"]["height"]
            or inputs["10"]["width"] != subject["width"]
            or inputs["10"]["height"] != subject["height"]
            or inputs["11"]["x"] != subject["x"]
            or inputs["11"]["y"] != subject["y"]
            or inputs["12"]["left"] != layout["feather_pixels"]
            or inputs["14"]["grow_mask_by"] != layout["vae_grow_mask_by"]
        ):
            raise _unsafe("Two-stage workflow layout bindings drifted.")


def _validate_workflow(
    graph: object,
    binding: object,
    available_models: Collection[str],
    allowed_node_inputs: dict[str, frozenset[str]],
) -> dict[str, object]:
    if not isinstance(graph, dict) or not 1 <= len(graph) <= MAX_NODES:
        raise _unsafe("Workflow graph size is outside the reviewed limit.")
    if isinstance(available_models, (str, bytes)) or not isinstance(available_models, Collection):
        raise _unsafe("Available model names must be an explicit collection.")
    model_names = {
        _validate_model_name(item)
        for item in available_models
        if isinstance(item, str)
    }
    if len(model_names) != len(available_models):
        raise _unsafe("Available model names are invalid or duplicated.")

    normalized_graph = copy.deepcopy(graph)
    output_nodes: list[str] = []
    for node_id, node in normalized_graph.items():
        if not isinstance(node_id, str) or not node_id or not isinstance(node, dict):
            raise _unsafe("Workflow node IDs and records must be objects.")
        if set(node) != {"class_type", "inputs"}:
            raise _unsafe("Workflow nodes contain unreviewed fields.", node_id)
        class_type = node.get("class_type")
        inputs = node.get("inputs")
        if (
            not isinstance(class_type, str)
            or class_type not in allowed_node_inputs
            or any(term in class_type.lower() for term in FORBIDDEN_TERMS)
            or not isinstance(inputs, dict)
        ):
            raise _unsafe("Workflow contains an unknown or unapproved node.", node_id)
        if any(
            not isinstance(key, str)
            or key not in allowed_node_inputs[class_type]
            or any(term in key.lower() for term in FORBIDDEN_TERMS)
            for key in inputs
        ):
            raise _unsafe("Workflow contains unreviewed node inputs.", node_id)
        if class_type == "SaveImage":
            output_nodes.append(node_id)

    if len(output_nodes) != 1:
        raise _unsafe("Workflow must have one unambiguous owned output.")
    _validate_edges(normalized_graph)
    normalized_binding = _validate_binding(binding, normalized_graph, output_nodes[0])
    _enforce_resource_limits(normalized_graph)
    _enforce_model_names(normalized_graph, model_names)
    return {
        "graph": normalized_graph,
        "binding": normalized_binding,
        "output_node": output_nodes[0],
    }


def _validate_shipped_document(value: object) -> dict[str, object]:
    if isinstance(value, dict) and value.get("template_id") == TWO_STAGE_TEMPLATE_ID:
        return _validate_two_stage_shipped_document(value)
    standard_fields = {
        "schema_version",
        "template_id",
        "template_version",
        "operation",
        "model_families",
        "allowed_node_classes",
        "output_node",
        "bindings",
        "graph",
    }
    regional_fields = standard_fields | {"layout_mode", "regional_bindings"}
    if not isinstance(value, dict) or set(value) not in {
        frozenset(standard_fields),
        frozenset(regional_fields),
    }:
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed workflow template fields are invalid.",
        )
    is_regional = set(value) == regional_fields
    if (
        value["schema_version"] != 1
        or type(value["template_version"]) is not int
        or value["template_version"] <= 0
        or not isinstance(value["template_id"], str)
        or TEMPLATE_ID_PATTERN.fullmatch(value["template_id"]) is None
        or value["operation"] not in OPERATIONS
        or not _valid_families(value["model_families"])
        or not isinstance(value["output_node"], str)
    ):
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed workflow template metadata is invalid.",
        )
    allowed = value["allowed_node_classes"]
    graph = value["graph"]
    allowed_node_inputs = (
        SHIPPED_REGIONAL_NODE_INPUTS if is_regional else SAFE_NODE_INPUTS
    )
    if (
        not isinstance(allowed, list)
        or len(set(allowed)) != len(allowed)
        or any(item not in allowed_node_inputs for item in allowed)
        or not isinstance(graph, dict)
        or set(allowed) != {
            node.get("class_type") for node in graph.values() if isinstance(node, dict)
        }
    ):
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed workflow node allowlist is invalid.",
        )
    if is_regional and (
        value["template_id"] != REGIONAL_TEMPLATE_ID
        or value["layout_mode"] != LAYOUT_MODE
        or value["operation"] != "txt2img"
        or value["model_families"] != ["sdxl"]
        or sum(
            node.get("class_type") == "ConditioningSetAreaPercentage"
            for node in graph.values()
            if isinstance(node, dict)
        )
        != 2
        or sum(
            node.get("class_type") == "ConditioningCombine"
            for node in graph.values()
            if isinstance(node, dict)
        )
        != 2
    ):
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed regional workflow metadata or node counts are invalid.",
        )
    available = _primary_model_names(graph)
    try:
        validator = (
            _validate_reviewed_regional_workflow
            if is_regional
            else validate_imported_workflow
        )
        validated = validator(
            graph,
            {**value["bindings"], "output": [value["output_node"]]},
            available,
        )
        regional_bindings = None
        if is_regional:
            regional_bindings = _validate_regional_bindings(
                value["regional_bindings"],
                validated["graph"],
                validated["binding"],
            )
            validate_regional_layout(
                _regional_layout_from_graph(validated["graph"], regional_bindings)
            )
    except ValidationError as error:
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed workflow graph is unsafe.",
        ) from error
    document = copy.deepcopy(value)
    document["graph"] = validated["graph"]
    document["bindings"] = {
        key: path for key, path in validated["binding"].items() if key != "output"
    }
    if is_regional:
        document["regional_bindings"] = regional_bindings
    document["workflow_sha256"] = _canonical_hash(value)
    return document


def _validate_two_stage_shipped_document(value: object) -> dict[str, object]:
    fields = {
        "schema_version",
        "template_id",
        "template_version",
        "operation",
        "model_families",
        "layout_mode",
        "stage_contract",
        "allowed_node_classes",
        "output_nodes",
        "bindings",
        "graph",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed two-stage workflow fields are invalid.",
        )
    allowed = value["allowed_node_classes"]
    graph = value["graph"]
    if (
        value["schema_version"] != 1
        or value["template_id"] != TWO_STAGE_TEMPLATE_ID
        or value["template_version"] != 1
        or value["operation"] != "txt2img"
        or value["model_families"] != ["sdxl"]
        or value["layout_mode"] != TWO_STAGE_LAYOUT_MODE
        or value["stage_contract"] != "base-subject-v1"
        or value["output_nodes"] != TWO_STAGE_OUTPUT_NODES
        or value["bindings"] != TWO_STAGE_BINDINGS
        or not isinstance(allowed, list)
        or any(not isinstance(item, str) for item in allowed)
        or len(allowed) != len(set(allowed))
        or set(allowed) != set(TWO_STAGE_NODE_CLASSES.values())
        or any(item not in SHIPPED_TWO_STAGE_NODE_INPUTS for item in allowed)
    ):
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed two-stage workflow metadata or bindings are invalid.",
        )
    try:
        normalized_graph = _validate_two_stage_graph(
            graph,
            _primary_model_names(graph),
            template_scalars=True,
        )
    except (ValidationError, ValueError) as error:
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed two-stage workflow graph is unsafe.",
        ) from error
    document = copy.deepcopy(value)
    document["graph"] = normalized_graph
    document["workflow_sha256"] = _canonical_hash(value)
    return document


def _validate_registered_document(value: object, digest: str) -> dict[str, object]:
    fields = {
        "schema_version",
        "template_id",
        "template_version",
        "workflow_sha256",
        "operation",
        "model_families",
        "bindings",
        "output_node",
        "graph",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid registration fields")
    if (
        value["schema_version"] != 1
        or value["template_id"] != f"imported:{digest}"
        or value["template_version"] != 1
        or value["workflow_sha256"] != digest
        or value["operation"] not in OPERATIONS
        or value["model_families"] != ["unknown"]
        or not isinstance(value["output_node"], str)
        or not isinstance(value["bindings"], dict)
    ):
        raise ValueError("invalid registration metadata")
    payload = {
        "operation": value["operation"],
        "model_families": value["model_families"],
        "bindings": value["bindings"],
        "output_node": value["output_node"],
        "graph": value["graph"],
    }
    if _canonical_hash(payload) != digest:
        raise ValueError("registration digest mismatch")
    available = _primary_model_names(value["graph"])
    validated = validate_imported_workflow(
        value["graph"],
        {**value["bindings"], "output": [value["output_node"]]},
        available,
    )
    return {
        **copy.deepcopy(value),
        "graph": validated["graph"],
        "bindings": {
            key: path for key, path in validated["binding"].items() if key != "output"
        },
    }


def _validate_binding(
    value: object,
    graph: dict[str, object],
    output_node: str,
) -> dict[str, list[str]]:
    if not isinstance(value, dict) or set(value) != REQUIRED_BINDINGS:
        raise _unsafe("Workflow parameter bindings are incomplete or unexpected.")
    normalized: dict[str, list[str]] = {}
    targets: set[tuple[str, ...]] = set()
    for key, path in value.items():
        expected_length = 1 if key == "output" else 3
        if (
            not isinstance(path, list)
            or len(path) != expected_length
            or any(not isinstance(item, str) or not item for item in path)
        ):
            raise _unsafe("Workflow binding paths are invalid.")
        target = tuple(path)
        if target in targets:
            raise _unsafe("Workflow bindings must target distinct fields.")
        targets.add(target)
        if key == "output":
            if path[0] != output_node:
                raise _unsafe("Workflow output binding is ambiguous.")
        else:
            node = graph.get(path[0])
            if (
                path[1] != "inputs"
                or not isinstance(node, dict)
                or not isinstance(node.get("inputs"), dict)
                or path[2] not in node["inputs"]
                or isinstance(node["inputs"][path[2]], (dict, list))
            ):
                raise _unsafe("Workflow binding must resolve to an existing scalar input.")
        normalized[key] = list(path)
    model_node = graph[normalized["model"][0]]
    output = graph[output_node]
    model_class = model_node["class_type"]
    if (
        model_class not in MODEL_LOADER_INPUTS
        or normalized["model"][2] != MODEL_LOADER_INPUTS[model_class]
        or output["class_type"] != "SaveImage"
    ):
        raise _unsafe("Workflow model or output binding targets the wrong node class.")
    return normalized


def _validate_edges(graph: dict[str, object]) -> None:
    for node_id, node in graph.items():
        for value in node["inputs"].values():
            if isinstance(value, list):
                if (
                    len(value) != 2
                    or not isinstance(value[0], str)
                    or value[0] not in graph
                    or type(value[1]) is not int
                    or value[1] < 0
                ):
                    raise _unsafe("Workflow contains an invalid node edge.", node_id)
            elif isinstance(value, dict) or value is None or not isinstance(
                value,
                (str, int, float, bool),
            ):
                raise _unsafe("Workflow contains an unsupported input value.", node_id)


def _enforce_resource_limits(graph: dict[str, object]) -> None:
    for node_id, node in graph.items():
        inputs = node["inputs"]
        class_type = node["class_type"]
        if "batch_size" in inputs and inputs["batch_size"] != 1:
            raise _unsafe("Workflow batch size must be exactly one.", node_id)
        if "steps" in inputs and (
            type(inputs["steps"]) is not int or not 1 <= inputs["steps"] <= MAX_STEPS
        ):
            raise _unsafe("Workflow steps exceed the reviewed limit.", node_id)
        if class_type in {"EmptyLatentImage", "EmptySD3LatentImage"}:
            for key in ("width", "height"):
                if key not in inputs:
                    continue
                if (
                    type(inputs[key]) is not int
                    or not MIN_DIMENSION <= inputs[key] <= MAX_DIMENSION
                    or inputs[key] % 8 != 0
                ):
                    raise _unsafe(
                        "Workflow dimensions are outside the reviewed limit.",
                        node_id,
                    )
        if class_type == "ConditioningSetAreaPercentage":
            if any(
                not _finite_number(inputs[key])
                for key in ("x", "y", "width", "height", "strength")
            ):
                raise _unsafe("Regional workflow scalars must be finite.", node_id)
            if (
                not 0.0 <= float(inputs["x"]) < 1.0
                or not 0.0 <= float(inputs["y"]) < 1.0
                or not 0.0 < float(inputs["width"]) <= 1.0
                or not 0.0 < float(inputs["height"]) <= 1.0
                or not 0.0 <= float(inputs["strength"]) <= 2.0
                or float(inputs["x"]) + float(inputs["width"]) > 1.0
                or float(inputs["y"]) + float(inputs["height"]) > 1.0
            ):
                raise _unsafe("Regional workflow scalars are outside limits.", node_id)
        if "seed" in inputs and (
            type(inputs["seed"]) is not int or not 0 <= inputs["seed"] <= MAX_SEED
        ):
            raise _unsafe("Workflow seed is outside the reviewed limit.", node_id)
        if "cfg" in inputs and (
            not _number(inputs["cfg"]) or not 0 < float(inputs["cfg"]) <= 30
        ):
            raise _unsafe("Workflow guidance is outside the reviewed limit.", node_id)
        if "denoise" in inputs and (
            not _number(inputs["denoise"]) or not 0 <= float(inputs["denoise"]) <= 1
        ):
            raise _unsafe("Workflow denoise is outside the reviewed limit.", node_id)
        for field in ("ckpt_name", "unet_name", "clip_name", "vae_name"):
            if field in inputs and (
                not isinstance(inputs[field], str)
                or not _safe_relative_path(inputs[field])
            ):
                raise _unsafe("Workflow model component name is unsafe.", node_id)
        if class_type == "UNETLoader" and inputs.get("weight_dtype") != "default":
            raise _unsafe("Workflow UNet precision is outside the reviewed route.", node_id)
        if class_type == "CLIPLoader" and (
            inputs.get("type") not in {"lumina2", "stable_diffusion"}
            or inputs.get("device", "default") != "default"
        ):
            raise _unsafe("Workflow text encoder settings are outside the reviewed routes.", node_id)
        if class_type == "ModelSamplingAuraFlow" and inputs.get("shift") != 3.0:
            raise _unsafe("Workflow sampling shift is outside the reviewed route.", node_id)
        if class_type == "SaveImage" and inputs.get("filename_prefix") != "local-gpu-imagegen":
            raise _unsafe("Workflow output prefix is outside the owned namespace.", node_id)
        if class_type in {"LoadImage", "LoadImageMask"}:
            image = inputs.get("image")
            if not isinstance(image, str) or not _safe_relative_path(image):
                raise _unsafe("Workflow input image path is unsafe.", node_id)


def _enforce_model_names(
    graph: dict[str, object],
    available_models: set[str],
) -> None:
    loaders = [node for node in graph.values() if node["class_type"] in MODEL_LOADER_INPUTS]
    if len(loaders) != 1:
        raise _unsafe("Workflow must contain exactly one primary model loader.")
    loader = loaders[0]
    model = loader["inputs"].get(MODEL_LOADER_INPUTS[loader["class_type"]])
    if not isinstance(model, str) or model not in available_models:
        raise _unsafe("Workflow model is not in the displayed backend inventory.")


def _validate_parameters(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != PARAMETER_KEYS:
        raise ValidationError(
            "invalid_workflow_parameters",
            "Workflow parameters are incomplete or unexpected.",
        )
    prompts = (value["positive_prompt"], value["negative_prompt"])
    if any(not isinstance(item, str) for item in prompts):
        raise _invalid_parameters()
    if (
        type(value["seed"]) is not int
        or not 0 <= value["seed"] <= MAX_SEED
        or type(value["steps"]) is not int
        or not 1 <= value["steps"] <= MAX_STEPS
        or not _number(value["guidance_scale"])
        or not 0 < float(value["guidance_scale"]) <= 30
        or not isinstance(value["sampler"], str)
        or not value["sampler"].strip()
        or not isinstance(value["scheduler"], str)
        or not value["scheduler"].strip()
    ):
        raise _invalid_parameters()
    for key in ("width", "height"):
        dimension = value[key]
        if (
            type(dimension) is not int
            or not MIN_DIMENSION <= dimension <= MAX_DIMENSION
            or dimension % 8 != 0
        ):
            raise _invalid_parameters()
    return copy.deepcopy(value)


def _set_binding(
    graph: dict[str, object],
    path: list[str],
    value: object,
) -> None:
    graph[path[0]][path[1]][path[2]] = copy.deepcopy(value)


def _read_source_graph(path: Path) -> dict[str, object]:
    try:
        value = _read_bounded_json(path)
    except ArtifactError as error:
        raise ArtifactError(
            "invalid_workflow_source",
            "Imported workflow source must be bounded, regular, and valid JSON.",
        ) from error
    if not isinstance(value, dict):
        raise ArtifactError(
            "invalid_workflow_source",
            "Imported workflow source must contain a graph object.",
        )
    return value


def _read_bounded_json(path: Path) -> object:
    try:
        file_stat = os.stat(path, follow_symlinks=False)
        if (
            _link_like(path)
            or not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size > MAX_SOURCE_BYTES
        ):
            raise OSError("unsafe workflow file")
        encoded = path.read_bytes()
        if len(encoded) > MAX_SOURCE_BYTES:
            raise OSError("oversized workflow file")
        return json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactError(
            "invalid_workflow_source",
            "Workflow JSON is unreadable or unsafe.",
        ) from error


def _primary_model_names(graph: object) -> list[str]:
    if not isinstance(graph, dict):
        raise ValueError("invalid graph")
    names = []
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        input_name = MODEL_LOADER_INPUTS.get(class_type)
        inputs = node.get("inputs")
        if (
            input_name is not None
            and isinstance(inputs, dict)
            and isinstance(inputs.get(input_name), str)
        ):
            names.append(inputs[input_name])
    return names


def _infer_operation(graph: dict[str, object]) -> str:
    classes = {node["class_type"] for node in graph.values()}
    if "VAEEncodeForInpaint" in classes or "LoadImageMask" in classes:
        return "inpaint"
    if "VAEEncode" in classes or "LoadImage" in classes:
        return "img2img"
    return "txt2img"


def _freeze_single_import_model(
    graph: dict[str, object],
    binding: object,
    available_models: Collection[str],
) -> None:
    if (
        isinstance(available_models, (str, bytes))
        or not isinstance(available_models, Collection)
        or len(available_models) != 1
        or not isinstance(binding, dict)
    ):
        return
    model = next(iter(available_models))
    path = binding.get("model")
    if (
        not isinstance(model, str)
        or not isinstance(path, list)
        or len(path) != 3
        or any(not isinstance(item, str) for item in path)
    ):
        return
    try:
        _set_binding(graph, path, _validate_model_name(model))
    except (KeyError, TypeError):
        return


def _validate_model_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or not _safe_relative_path(value):
        raise _unsafe("Workflow model name must be a safe backend-relative name.")
    return value.strip()


def _safe_relative_path(value: str) -> bool:
    if "\x00" in value:
        return False
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value.replace("\\", "/"))
    return (
        not windows.is_absolute()
        and not windows.drive
        and not posix.is_absolute()
        and all(part not in {"", ".", ".."} for part in posix.parts)
    )


def _valid_families(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and len(set(value)) == len(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same_typed_scalar(value: object, expected: object) -> bool:
    return type(value) is type(expected) and value == expected


def _finite_number(value: object) -> bool:
    return _number(value) and math.isfinite(float(value))


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unsafe(message: str, node_id: str | None = None) -> ValidationError:
    details = {"node_id": node_id} if node_id is not None else None
    return ValidationError("unsafe_comfy_workflow", message, details)


def _invalid_parameters() -> ValidationError:
    return ValidationError(
        "invalid_workflow_parameters",
        "Workflow parameters are outside the reviewed limits.",
    )


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    path_stat = os.lstat(path)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)
