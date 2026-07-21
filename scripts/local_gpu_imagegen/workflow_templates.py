from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Collection
from pathlib import Path, PurePosixPath, PureWindowsPath

from .artifacts import atomic_write_json
from .errors import ArtifactError, ConflictError, ValidationError


SAFE_NODE_INPUTS = {
    "CheckpointLoaderSimple": frozenset({"ckpt_name"}),
    "CLIPTextEncode": frozenset({"text", "clip"}),
    "EmptyLatentImage": frozenset({"width", "height", "batch_size"}),
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
OPERATIONS = frozenset({"txt2img", "img2img", "inpaint"})
MAX_NODES = 64
MAX_STEPS = 80
MIN_DIMENSION = 256
MAX_DIMENSION = 1536
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SEED = 2**64 - 1
TEMPLATE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
IMPORTED_ID_PATTERN = re.compile(r"^imported:([0-9a-f]{64})$")


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
        validate_imported_workflow(
            graph,
            {**bindings, "output": [template["output_node"]]},
            [normalized_model],
        )
        families = template["model_families"]
        model_family = "sd15" if "sd15" in families else families[0]
        return {
            "template_id": template["template_id"],
            "template_version": template["template_version"],
            "workflow_sha256": template["workflow_sha256"],
            "operation": template["operation"],
            "model_family": model_family,
            "output_node": template["output_node"],
            "graph": graph,
        }

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


def validate_imported_workflow(
    graph: object,
    binding: object,
    available_models: Collection[str],
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
            or class_type not in SAFE_NODE_CLASSES
            or any(term in class_type.lower() for term in FORBIDDEN_TERMS)
            or not isinstance(inputs, dict)
        ):
            raise _unsafe("Workflow contains an unknown or unapproved node.", node_id)
        if any(
            not isinstance(key, str)
            or key not in SAFE_NODE_INPUTS[class_type]
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
    fields = {
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
    if not isinstance(value, dict) or set(value) != fields:
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed workflow template fields are invalid.",
        )
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
    if (
        not isinstance(allowed, list)
        or len(set(allowed)) != len(allowed)
        or any(item not in SAFE_NODE_CLASSES for item in allowed)
        or not isinstance(graph, dict)
        or set(allowed) != {
            node.get("class_type") for node in graph.values() if isinstance(node, dict)
        }
    ):
        raise ArtifactError(
            "invalid_workflow_template",
            "Reviewed workflow node allowlist is invalid.",
        )
    available = _checkpoint_names(graph)
    try:
        validated = validate_imported_workflow(
            graph,
            {**value["bindings"], "output": [value["output_node"]]},
            available,
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
    available = _checkpoint_names(value["graph"])
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
    if (
        model_node["class_type"] != "CheckpointLoaderSimple"
        or normalized["model"][2] != "ckpt_name"
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
        if "batch_size" in inputs and inputs["batch_size"] != 1:
            raise _unsafe("Workflow batch size must be exactly one.", node_id)
        if "steps" in inputs and (
            type(inputs["steps"]) is not int or not 1 <= inputs["steps"] <= MAX_STEPS
        ):
            raise _unsafe("Workflow steps exceed the reviewed limit.", node_id)
        for key in ("width", "height"):
            if key in inputs and (
                type(inputs[key]) is not int
                or not MIN_DIMENSION <= inputs[key] <= MAX_DIMENSION
                or inputs[key] % 8 != 0
            ):
                raise _unsafe("Workflow dimensions are outside the reviewed limit.", node_id)
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
        class_type = node["class_type"]
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
    loaders = [
        node
        for node in graph.values()
        if node["class_type"] == "CheckpointLoaderSimple"
    ]
    if len(loaders) != 1:
        raise _unsafe("Workflow must contain exactly one checkpoint loader.")
    model = loaders[0]["inputs"].get("ckpt_name")
    if not isinstance(model, str) or model not in available_models:
        raise _unsafe("Workflow checkpoint is not in the displayed backend inventory.")


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


def _checkpoint_names(graph: object) -> list[str]:
    if not isinstance(graph, dict):
        raise ValueError("invalid graph")
    names = []
    for node in graph.values():
        if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple":
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and isinstance(inputs.get("ckpt_name"), str):
                names.append(inputs["ckpt_name"])
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
