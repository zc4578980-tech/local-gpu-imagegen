from __future__ import annotations

import copy
import json
import os
import re
import struct
import tempfile
import time
import urllib.parse
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..artifacts import PNG_SIGNATURE, validate_png
from ..errors import (
    ArtifactError,
    AssetEngineError,
    ConflictError,
    StateError,
    ValidationError,
)
from ..model_identity import identity_token, validate_discovery_record
from ..regional_layout import (
    LAYOUT_MODE,
    REGIONAL_TEMPLATE_ID,
    validate_regional_conditioning,
    validate_regional_layout,
    validate_regional_node_info,
)
from ..two_stage_layout import (
    TWO_STAGE_LAYOUT_MODE,
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
    derive_subject_seed,
    validate_two_stage_conditioning,
    validate_two_stage_layout,
    validate_two_stage_node_info,
)
from ..workflow_templates import (
    COMPONENT_LOADER_INPUTS,
    FORBIDDEN_TERMS,
    MAX_DIMENSION,
    MAX_NODES,
    MAX_SEED,
    MAX_STEPS,
    MIN_DIMENSION,
    MODEL_LOADER_INPUTS,
    REGIONAL_NODE_INPUTS,
    SAFE_NODE_INPUTS,
    TWO_STAGE_OUTPUT_NODES,
    _validate_rendered_two_stage_workflow,
)
from .base import BoundedJsonClient


MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_COMFY_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_COMFY_REQUEST_BYTES = 16 * 1024 * 1024
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MODES = frozenset({"txt2img", "img2img", "inpaint"})
REGIONAL_SAFE_NODE_INPUTS = {**SAFE_NODE_INPUTS, **REGIONAL_NODE_INPUTS}
DISAPPEARED_GRACE_POLLS = 4
TWO_STAGE_LIVE_CLASSES = (
    "VAEEncodeForInpaint",
    "SolidMask",
    "MaskComposite",
    "FeatherMask",
    "ImageCompositeMasked",
    "MaskToImage",
)


class ComfyUIAdapter:
    backend_id = "comfyui"

    def __init__(
        self,
        base_url: str,
        *,
        lan_confirmation: str | None = None,
        poll_interval: float = 0.25,
        timeout: float = 600,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            not isinstance(poll_interval, (int, float))
            or isinstance(poll_interval, bool)
            or poll_interval < 0
            or not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout < 0
            or not callable(clock)
            or not callable(sleep)
        ):
            raise ValidationError(
                "invalid_backend_timeout",
                "ComfyUI polling settings must be non-negative and callable.",
            )
        self.client = BoundedJsonClient(
            base_url,
            lan_confirmation=lan_confirmation,
            timeout=min(max(float(timeout), 1.0), 30.0),
            max_bytes=MAX_COMFY_RESPONSE_BYTES,
            max_request_bytes=MAX_COMFY_REQUEST_BYTES,
        )
        self.base_url = self.client.base_url
        self.endpoint_identity = self.client.endpoint_identity
        self.poll_interval = float(poll_interval)
        self.timeout = float(timeout)
        self.clock = clock
        self.sleep = sleep

    def probe(self) -> dict[str, object]:
        stats = self.client.get_json("/system_stats")
        if not isinstance(stats, dict):
            raise ArtifactError(
                "invalid_backend_response",
                "ComfyUI system statistics must be an object.",
            )
        version = _nested_version(stats)
        return {
            "backend": self.backend_id,
            "implementation": "ComfyUI",
            "version": version,
            "endpoint_identity": self.endpoint_identity,
            "endpoint_class": self.client.endpoint_class,
            "ready": True,
        }

    def discover(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for loader_class, input_name in COMPONENT_LOADER_INPUTS.items():
            try:
                info = self.client.get_json(f"/object_info/{loader_class}")
            except AssetEngineError as error:
                raise StateError(
                    "api_inventory_failed",
                    "ComfyUI is healthy but its model inventory API failed.",
                    {
                        "backend_error": error.code,
                        "loader_class": loader_class,
                        "recoverable_next_actions": [
                            "retry_api_inventory",
                            "inspect_comfyui_logs",
                        ],
                    },
                ) from error
            names = _loader_choices(info, loader_class, input_name)
            for name in sorted(names):
                record = validate_discovery_record({
                    "backend": self.backend_id,
                    "endpoint_identity": self.endpoint_identity,
                    "backend_model_id": name,
                    "format": Path(name.replace("\\", "/")).suffix.lower() or "unknown",
                    "byte_size": None,
                    "modified_ns": None,
                    "sha256": None,
                    "identity_strength": "backend_binding",
                    "metadata": {
                        "loader_class": loader_class,
                        "loader_input": input_name,
                    },
                })
                record["identity_token"] = identity_token(record)
                records.append(record)
        has_primary_model = any(
            record["metadata"]["loader_class"]
            in {"CheckpointLoaderSimple", "UNETLoader"}
            for record in records
        )
        if not has_primary_model:
            raise StateError(
                "no_models_installed",
                "ComfyUI inventory succeeded but no supported model files are installed.",
                {
                    "recoverable_next_actions": [
                        "install_supported_model",
                        "retry_api_inventory",
                    ]
                },
            )
        return records

    def layout_capability(self, mode: str) -> dict[str, object]:
        if mode not in {LAYOUT_MODE, TWO_STAGE_LAYOUT_MODE}:
            return {
                "mode": mode,
                "available": False,
                "endpoint_identity": self.endpoint_identity,
                "reason": "unsupported_layout_mode",
            }
        try:
            if mode == LAYOUT_MODE:
                area = self.client.get_json(
                    "/object_info/ConditioningSetAreaPercentage"
                )
                combine = self.client.get_json("/object_info/ConditioningCombine")
                validate_regional_node_info(area, combine)
            else:
                node_info: dict[str, object] = {}
                for class_name in TWO_STAGE_LIVE_CLASSES:
                    value = self.client.get_json(f"/object_info/{class_name}")
                    if isinstance(value, dict):
                        node_info[class_name] = value.get(class_name)
                validate_two_stage_node_info(node_info)
        except AssetEngineError as error:
            return {
                "mode": mode,
                "available": False,
                "endpoint_identity": self.endpoint_identity,
                "reason": error.code,
            }
        return {
            "mode": mode,
            "available": True,
            "endpoint_identity": self.endpoint_identity,
            "reason": None,
        }

    def generate(self, request: dict[str, object]) -> dict[str, object]:
        normalized = _validate_request(request, self.endpoint_identity)
        layout_mode = normalized["workflow"].get("layout_mode")
        recovery_job_id = normalized.get("recovery_job_id")
        if recovery_job_id is None and layout_mode == LAYOUT_MODE:
            capability = self.layout_capability(LAYOUT_MODE)
            if capability["available"] is not True:
                raise ConflictError(
                    "regional_layout_drifted",
                    "Required ComfyUI regional nodes changed before submission.",
                )
        elif recovery_job_id is None and layout_mode == TWO_STAGE_LAYOUT_MODE:
            capability = self.layout_capability(TWO_STAGE_LAYOUT_MODE)
            if capability["available"] is not True:
                raise ConflictError(
                    "two_stage_layout_drifted",
                    "Required ComfyUI two-stage nodes changed before submission.",
                )
        if recovery_job_id is None:
            submitted = self.client.post_json(
                "/prompt",
                {
                    "prompt": normalized["workflow"]["graph"],
                    "client_id": normalized["idempotency_key"],
                },
            )
            job_id = _require_job_id(submitted)
            callback = normalized.get("backend_job_callback")
            if callable(callback):
                callback(job_id)
        else:
            job_id = _validate_job_id(recovery_job_id)
        history = self._poll(job_id)
        model = normalized["model"]
        workflow = normalized["workflow"]
        result = {
            "ok": True,
            "backend": self.backend_id,
            "mode": normalized["mode"],
            "model": model["backend_model_id"],
            "endpoint_identity": self.endpoint_identity,
            "model_identity_token": model["identity_token"],
            "identity_strength": model["identity_strength"],
            "workflow_template_id": workflow["template_id"],
            "workflow_template_version": workflow["template_version"],
            "workflow_job_id": job_id,
            "prompt_compiler_id": normalized["prompt_compiler_id"],
            "prompt_compiler_version": normalized["prompt_compiler_version"],
            "width": normalized["width"],
            "height": normalized["height"],
            "steps": normalized["steps"],
            "guidance_scale": normalized["guidance_scale"],
            "sampler": normalized["sampler"],
            "scheduler": normalized["scheduler"],
            "seed": normalized["seed"],
        }
        if layout_mode == TWO_STAGE_LAYOUT_MODE:
            roles = _owned_outputs(history, job_id, workflow["output_nodes"])
            output_paths = normalized["output_paths"]
            written: dict[str, dict[str, str]] = {}
            for role in ("base", "mask", "final"):
                image = self.client.get_bytes(
                    _view_path(roles[role]),
                    max_bytes=MAX_IMAGE_BYTES,
                )
                output_path = Path(output_paths[role])
                _write_validated_png(output_path, image)
                written[role] = {"path": str(output_path.absolute())}
            result.update({
                "path": written["final"]["path"],
                "stage_outputs": {
                    "base": written["base"],
                    "final": written["final"],
                },
                "mask_output": written["mask"],
                "subject_seed": derive_subject_seed(normalized["seed"]),
                "control_sha256": workflow["control_sha256"],
                "component_bundle_sha256": normalized["component_bundle_sha256"],
            })
            return result

        output = _owned_output(
            history,
            job_id,
            str(workflow["output_node"]),
        )
        image = self.client.get_bytes(_view_path(output), max_bytes=MAX_IMAGE_BYTES)
        output_path = Path(str(normalized["output_path"]))
        _write_validated_png(output_path, image)
        result["path"] = str(output_path.absolute())
        return result

    def cancel_or_query(
        self,
        job_id: str,
        *,
        cancel: bool = False,
    ) -> dict[str, object]:
        normalized_job_id = _validate_job_id(job_id)
        state = self._query(normalized_job_id)
        if cancel and state["state"] == "queued":
            response = self.client.post_json("/queue", {"delete": [normalized_job_id]})
            if not isinstance(response, dict):
                raise ArtifactError(
                    "invalid_backend_response",
                    "ComfyUI queue deletion response must be an object.",
                )
            return {**state, "state": "cancel_requested"}
        return state

    def _poll(self, job_id: str) -> dict[str, object]:
        started = self.clock()
        disappeared_polls = 0
        while True:
            history = self._history(job_id)
            state = _history_state(history, job_id)
            if state == "completed":
                return history
            if state in {"rejected", "canceled"}:
                raise StateError(
                    f"comfyui_job_{state}",
                    f"ComfyUI job was {state}.",
                    {"job_id": job_id},
                )
            queue_state = self._queue_state(job_id)
            if queue_state == "disappeared" and state == "absent":
                disappeared_polls += 1
                if disappeared_polls > DISAPPEARED_GRACE_POLLS:
                    raise StateError(
                        "comfyui_job_disappeared",
                        "ComfyUI job disappeared after submission.",
                        {"job_id": job_id},
                    )
            else:
                disappeared_polls = 0
            if self.clock() - started >= self.timeout:
                final_state = self._query(job_id)
                raise StateError(
                    "comfyui_job_timed_out",
                    "ComfyUI job did not finish within the confirmed timeout.",
                    {"job_id": job_id, "state": final_state["state"]},
                )
            self.sleep(self.poll_interval)

    def _query(self, job_id: str) -> dict[str, object]:
        history = self._history(job_id)
        state = _history_state(history, job_id)
        if state != "absent":
            return {
                "job_id": job_id,
                "state": state,
                "cancel_supported": False,
            }
        state = self._queue_state(job_id)
        return {
            "job_id": job_id,
            "state": state,
            "cancel_supported": state == "queued",
        }

    def _history(self, job_id: str) -> dict[str, object]:
        value = self.client.get_json(
            "/history/" + urllib.parse.quote(job_id, safe="")
        )
        if not isinstance(value, dict):
            raise ArtifactError(
                "invalid_backend_response",
                "ComfyUI history response must be an object.",
            )
        entry = value.get(job_id)
        if entry is not None and not isinstance(entry, dict):
            raise ArtifactError(
                "invalid_backend_response",
                "ComfyUI history entry must be an object.",
            )
        return value

    def _queue_state(self, job_id: str) -> str:
        value = self.client.get_json("/queue")
        if not isinstance(value, dict):
            raise ArtifactError(
                "invalid_backend_response",
                "ComfyUI queue response must be an object.",
            )
        running = _queue_job_ids(value.get("queue_running"), "running")
        pending = _queue_job_ids(value.get("queue_pending"), "pending")
        if job_id in running:
            return "running"
        if job_id in pending:
            return "queued"
        return "disappeared"


def _validate_request(value: object, endpoint_identity: str) -> dict[str, object]:
    required = {
        "backend",
        "idempotency_key",
        "mode",
        "model",
        "workflow",
        "positive_prompt",
        "negative_prompt",
        "width",
        "height",
        "steps",
        "guidance_scale",
        "sampler",
        "scheduler",
        "seed",
        "output_path",
        "prompt_compiler_id",
        "prompt_compiler_version",
    }
    if not isinstance(value, dict) or required - set(value):
        missing = sorted(required - set(value)) if isinstance(value, dict) else sorted(required)
        raise ValidationError(
            "invalid_backend_request",
            "ComfyUI generation request is incomplete.",
            {"fields": missing},
        )
    if value["backend"] != "comfyui" or value["mode"] not in MODES:
        raise ValidationError(
            "invalid_backend_request",
            "ComfyUI backend or operation is invalid.",
        )
    for field in (
        "idempotency_key",
        "positive_prompt",
        "sampler",
        "scheduler",
        "output_path",
        "prompt_compiler_id",
    ):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValidationError(
                "invalid_backend_request",
                f"ComfyUI {field} must be a non-empty string.",
            )
    if not isinstance(value["negative_prompt"], str):
        raise ValidationError(
            "invalid_backend_request",
            "ComfyUI negative_prompt must be a string.",
        )
    if JOB_ID_PATTERN.fullmatch(value["idempotency_key"]) is None:
        raise ValidationError(
            "invalid_backend_request",
            "ComfyUI idempotency key is invalid.",
        )
    if (
        type(value["width"]) is not int
        or type(value["height"]) is not int
        or not MIN_DIMENSION <= value["width"] <= MAX_DIMENSION
        or not MIN_DIMENSION <= value["height"] <= MAX_DIMENSION
        or value["width"] % 8
        or value["height"] % 8
        or type(value["steps"]) is not int
        or not 1 <= value["steps"] <= MAX_STEPS
        or not _number(value["guidance_scale"])
        or not 0 < float(value["guidance_scale"]) <= 30
        or type(value["seed"]) is not int
        or not 0 <= value["seed"] <= MAX_SEED
        or type(value["prompt_compiler_version"]) is not int
        or value["prompt_compiler_version"] < 1
    ):
        raise ValidationError(
            "invalid_backend_request",
            "ComfyUI generation parameters are outside the reviewed limits.",
        )

    model = validate_discovery_record(value["model"])
    supplied_token = value["model"].get("identity_token") if isinstance(value["model"], dict) else None
    if (
        model["backend"] != "comfyui"
        or model["endpoint_identity"] != endpoint_identity
        or supplied_token != identity_token(model)
    ):
        raise ConflictError(
            "backend_model_mismatch",
            "Confirmed ComfyUI model identity does not match this endpoint.",
        )
    model["identity_token"] = supplied_token
    workflow = _validate_resolved_workflow(value["workflow"], model, value)
    result = copy.deepcopy(value)
    result["model"] = model
    result["workflow"] = workflow
    if workflow.get("layout_mode") == TWO_STAGE_LAYOUT_MODE:
        output_paths = value.get("output_paths")
        component_bundle_sha256 = value.get("component_bundle_sha256")
        backend_job_callback = value.get("backend_job_callback")
        recovery_job_id = value.get("recovery_job_id")
        if (
            not isinstance(output_paths, dict)
            or set(output_paths) != {"base", "mask", "final"}
            or any(
                not isinstance(output_paths[role], str)
                or not output_paths[role].strip()
                for role in ("base", "mask", "final")
            )
        ):
            raise ValidationError(
                "invalid_backend_request",
                "Two-stage ComfyUI output paths are invalid.",
            )
        if (
            not isinstance(component_bundle_sha256, str)
            or SHA256_PATTERN.fullmatch(component_bundle_sha256) is None
        ):
            raise ValidationError(
                "invalid_backend_request",
                "Two-stage ComfyUI component bundle digest is invalid.",
            )
        if backend_job_callback is not None and not callable(backend_job_callback):
            raise ValidationError(
                "invalid_backend_request",
                "Two-stage backend job callback is invalid.",
            )
        if recovery_job_id is not None:
            result["recovery_job_id"] = _validate_job_id(recovery_job_id)
        identities = {
            _resolved_path_identity(output_paths[role])
            for role in ("base", "mask", "final")
        }
        if (
            len(identities) != 3
            or _resolved_path_identity(str(value["output_path"]))
            != _resolved_path_identity(output_paths["final"])
        ):
            raise ValidationError(
                "invalid_backend_request",
                "Two-stage ComfyUI output paths must be distinct and final-bound.",
            )
        result["output_paths"] = {
            role: output_paths[role]
            for role in ("base", "mask", "final")
        }
    return result


def _resolved_path_identity(value: str) -> str:
    return os.path.normcase(os.fspath(Path(value).resolve()))


def _validate_resolved_workflow(
    value: object,
    model: dict[str, object],
    request: dict[str, object],
) -> dict[str, object]:
    is_two_stage = (
        isinstance(value, dict)
        and (
            value.get("template_id") == TWO_STAGE_TEMPLATE_ID
            or value.get("layout_mode") == TWO_STAGE_LAYOUT_MODE
            or "output_nodes" in value
            or "control_sha256" in value
        )
    )
    if is_two_stage:
        return _validate_resolved_two_stage_workflow(value, model, request)
    required = {
        "template_id",
        "template_version",
        "workflow_sha256",
        "operation",
        "model_family",
        "output_node",
        "graph",
    }
    is_regional = (
        isinstance(value, dict) and value.get("layout_mode") == LAYOUT_MODE
    )
    expected_fields = required | ({"layout_mode"} if is_regional else set())
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved ComfyUI workflow fields are invalid.",
        )
    if is_regional:
        if (
            value["template_id"] != REGIONAL_TEMPLATE_ID
            or value["model_family"] != "sdxl"
        ):
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved regional workflow metadata is invalid.",
            )
        regional_layout = validate_regional_layout(request.get("regional_layout"))
        regional_conditioning = validate_regional_conditioning(
            request.get("regional_conditioning")
        )
    else:
        regional_layout = None
        regional_conditioning = None
        if (
            "regional_layout" in request
            or "regional_conditioning" in request
        ):
            raise ValidationError(
                "invalid_regional_conditioning",
                "Standard ComfyUI requests reject regional data.",
            )
    if (
        not isinstance(value["template_id"], str)
        or type(value["template_version"]) is not int
        or value["template_version"] < 1
        or not isinstance(value["workflow_sha256"], str)
        or SHA256_PATTERN.fullmatch(value["workflow_sha256"]) is None
        or value["operation"] != request["mode"]
        or not isinstance(value["model_family"], str)
        or not isinstance(value["output_node"], str)
    ):
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved ComfyUI workflow metadata is invalid.",
        )
    graph = value["graph"]
    if not isinstance(graph, dict) or not 1 <= len(graph) <= MAX_NODES:
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved ComfyUI graph size is invalid.",
        )
    outputs = []
    loaders: list[tuple[str, str]] = []
    samplers = []
    latent_nodes = []
    prompt_values = []
    class_counts: Counter[str] = Counter()
    area_nodes: dict[str, dict[str, object]] = {}
    combine_nodes: dict[str, dict[str, object]] = {}
    approved_node_inputs = (
        REGIONAL_SAFE_NODE_INPUTS if is_regional else SAFE_NODE_INPUTS
    )
    for node_id, node in graph.items():
        if (
            not isinstance(node_id, str)
            or not isinstance(node, dict)
            or set(node) != {"class_type", "inputs"}
            or node.get("class_type") not in approved_node_inputs
            or not isinstance(node.get("inputs"), dict)
        ):
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved ComfyUI graph contains an unapproved node.",
            )
        class_type = node["class_type"]
        inputs = node["inputs"]
        class_counts[class_type] += 1
        if any(
            key not in approved_node_inputs[class_type]
            or any(term in key.lower() for term in FORBIDDEN_TERMS)
            for key in inputs
        ):
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved ComfyUI graph contains unapproved inputs.",
            )
        _validate_node_edges(node_id, inputs, graph)
        if class_type == "SaveImage":
            outputs.append(node_id)
            if inputs.get("filename_prefix") != "local-gpu-imagegen":
                raise ValidationError(
                    "unsafe_comfy_workflow",
                    "Resolved ComfyUI output prefix is unsafe.",
                )
        elif class_type in MODEL_LOADER_INPUTS:
            loaders.append((class_type, inputs.get(MODEL_LOADER_INPUTS[class_type])))
        elif class_type == "KSampler":
            samplers.append(inputs)
        elif class_type in {"EmptyLatentImage", "EmptySD3LatentImage"}:
            latent_nodes.append(inputs)
        elif class_type == "CLIPTextEncode":
            prompt_values.append(inputs.get("text"))
        elif class_type == "ConditioningSetAreaPercentage":
            if set(inputs) != REGIONAL_NODE_INPUTS[class_type]:
                raise ValidationError(
                    "unsafe_comfy_workflow",
                    "Resolved regional area inputs are incomplete.",
                )
            area_nodes[node_id] = inputs
        elif class_type == "ConditioningCombine":
            if set(inputs) != REGIONAL_NODE_INPUTS[class_type]:
                raise ValidationError(
                    "unsafe_comfy_workflow",
                    "Resolved regional combine inputs are incomplete.",
                )
            combine_nodes[node_id] = inputs
        elif class_type in {"LoadImage", "LoadImageMask"}:
            image = inputs.get("image")
            if not isinstance(image, str) or not _safe_relative_path(image):
                raise ValidationError(
                    "unsafe_comfy_workflow",
                    "Resolved ComfyUI input image path is unsafe.",
                )
    metadata = model.get("metadata")
    expected_loader = (
        metadata.get("loader_class"),
        model["backend_model_id"],
    ) if isinstance(metadata, dict) else (None, model["backend_model_id"])
    expected_input = metadata.get("loader_input") if isinstance(metadata, dict) else None
    if (
        outputs != [value["output_node"]]
        or expected_loader[0] not in MODEL_LOADER_INPUTS
        or MODEL_LOADER_INPUTS[expected_loader[0]] != expected_input
        or loaders != [expected_loader]
    ):
        raise ConflictError(
            "backend_model_mismatch",
            "Resolved ComfyUI graph changed its confirmed model or output.",
        )
    if len(samplers) != 1:
        raise ValidationError("unsafe_comfy_workflow", "Resolved graph requires one sampler.")
    sampler = samplers[0]
    expected_sampler = {
        "seed": request["seed"],
        "steps": request["steps"],
        "cfg": request["guidance_scale"],
        "sampler_name": request["sampler"],
        "scheduler": request["scheduler"],
    }
    if any(sampler.get(key) != expected for key, expected in expected_sampler.items()):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved ComfyUI sampler does not match confirmed parameters.",
        )
    if latent_nodes and any(
        latent.get("width") != request["width"]
        or latent.get("height") != request["height"]
        or latent.get("batch_size") != 1
        for latent in latent_nodes
    ):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved ComfyUI dimensions do not match confirmed parameters.",
        )
    expected_prompts = [request["positive_prompt"], request["negative_prompt"]]
    if is_regional:
        expected_prompts.extend([
            regional_conditioning["copy_prompt"],
            regional_conditioning["subject_prompt"],
        ])
        _validate_regional_graph(
            graph,
            sampler,
            class_counts,
            area_nodes,
            combine_nodes,
            regional_layout,
            regional_conditioning,
            request["positive_prompt"],
            request["negative_prompt"],
        )
    if Counter(prompt_values) != Counter(expected_prompts):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved ComfyUI prompts do not match confirmed prompts.",
        )
    return copy.deepcopy(value)


def _validate_resolved_two_stage_workflow(
    value: object,
    model: dict[str, object],
    request: dict[str, object],
) -> dict[str, object]:
    fields = {
        "template_id",
        "template_version",
        "workflow_sha256",
        "operation",
        "model_family",
        "output_nodes",
        "graph",
        "layout_mode",
        "control_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved two-stage ComfyUI workflow fields are invalid.",
        )
    if (
        value["template_id"] != TWO_STAGE_TEMPLATE_ID
        or type(value["template_version"]) is not int
        or value["template_version"] != 1
        or value["layout_mode"] != TWO_STAGE_LAYOUT_MODE
        or value["operation"] != request["mode"]
        or value["operation"] != "txt2img"
        or value["model_family"] != "sdxl"
        or not isinstance(value["workflow_sha256"], str)
        or SHA256_PATTERN.fullmatch(value["workflow_sha256"]) is None
        or not isinstance(value["control_sha256"], str)
        or SHA256_PATTERN.fullmatch(value["control_sha256"]) is None
        or value["output_nodes"] != TWO_STAGE_OUTPUT_NODES
    ):
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved two-stage ComfyUI workflow metadata is invalid.",
        )
    if "regional_layout" in request or "regional_conditioning" in request:
        raise ValidationError(
            "invalid_two_stage_conditioning",
            "Two-stage ComfyUI requests reject regional data.",
        )
    layout = validate_two_stage_layout(request.get("two_stage_layout"))
    conditioning = validate_two_stage_conditioning(
        request.get("two_stage_conditioning")
    )
    if (
        request["width"] != layout["canvas"]["width"]
        or request["height"] != layout["canvas"]["height"]
        or value["control_sha256"]
        != build_control_identity(
            layout,
            value["workflow_sha256"],
            "base-subject-v1",
        )
    ):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved two-stage control does not match confirmed parameters.",
        )
    metadata = model.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("loader_class") != "CheckpointLoaderSimple"
        or metadata.get("loader_input") != "ckpt_name"
    ):
        raise ConflictError(
            "backend_model_mismatch",
            "Resolved two-stage model binding is invalid.",
        )
    graph = value["graph"]
    _validate_rendered_two_stage_workflow(
        graph,
        str(model["backend_model_id"]),
        two_stage_layout=layout,
    )
    assert isinstance(graph, dict)
    inputs = {node_id: node["inputs"] for node_id, node in graph.items()}
    expected_base = {
        "seed": request["seed"],
        "steps": request["steps"],
        "cfg": request["guidance_scale"],
        "sampler_name": request["sampler"],
        "scheduler": request["scheduler"],
        "denoise": 1.0,
    }
    expected_subject = {
        **expected_base,
        "seed": derive_subject_seed(request["seed"]),
        "denoise": conditioning["subject_denoise"],
    }
    if (
        inputs["3"]["text"] != request["positive_prompt"]
        or inputs["4"]["text"] != request["negative_prompt"]
        or inputs["7"]["text"] != conditioning["subject_prompt"]
        or inputs["8"]["text"] != conditioning["subject_negative_prompt"]
        or any(inputs["5"].get(key) != expected for key, expected in expected_base.items())
        or any(inputs["15"].get(key) != expected for key, expected in expected_subject.items())
    ):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved two-stage graph does not match confirmed parameters.",
        )
    return copy.deepcopy(value)


def _validate_regional_graph(
    graph: dict[str, object],
    sampler: dict[str, object],
    class_counts: Counter[str],
    area_nodes: dict[str, dict[str, object]],
    combine_nodes: dict[str, dict[str, object]],
    layout: dict[str, object],
    conditioning: dict[str, object],
    positive_prompt: str,
    negative_prompt: str,
) -> None:
    expected_counts = {
        "CLIPTextEncode": 4,
        "ConditioningSetAreaPercentage": 2,
        "ConditioningCombine": 2,
    }
    if any(class_counts[name] != count for name, count in expected_counts.items()):
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved regional workflow node counts are invalid.",
        )

    actual_areas = []
    for inputs in area_nodes.values():
        source_edge = inputs.get("conditioning")
        if not _exact_edge(source_edge):
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved regional area source is invalid.",
            )
        source = graph[source_edge[0]]
        source_inputs = source.get("inputs") if isinstance(source, dict) else None
        prompt = source_inputs.get("text") if isinstance(source_inputs, dict) else None
        if source.get("class_type") != "CLIPTextEncode" or not isinstance(prompt, str):
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved regional area prompt source is invalid.",
            )
        scalars = tuple(
            inputs.get(key)
            for key in ("x", "y", "width", "height", "strength")
        )
        if any(not _number(item) for item in scalars):
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved regional area scalars are invalid.",
            )
        actual_areas.append((prompt, *scalars))

    copy_region = layout["copy_region"]
    subject_region = layout["subject_region"]
    expected_areas = [
        (
            conditioning["copy_prompt"],
            copy_region["x"],
            copy_region["y"],
            copy_region["width"],
            copy_region["height"],
            conditioning["copy_strength"],
        ),
        (
            conditioning["subject_prompt"],
            subject_region["x"],
            subject_region["y"],
            subject_region["width"],
            subject_region["height"],
            conditioning["subject_strength"],
        ),
    ]
    if Counter(actual_areas) != Counter(expected_areas):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved ComfyUI regional areas do not match confirmed values.",
        )

    negative_edge = sampler.get("negative")
    if not _exact_edge(negative_edge):
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved regional negative conditioning edge is invalid.",
        )
    negative_node = graph[negative_edge[0]]
    if (
        negative_node.get("class_type") != "CLIPTextEncode"
        or negative_node.get("inputs", {}).get("text") != negative_prompt
    ):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved ComfyUI negative prompt does not match confirmation.",
        )

    visited_combines: set[str] = set()
    leaves = _conditioning_leaves(
        sampler.get("positive"),
        graph,
        combine_nodes,
        visited_combines,
    )
    if visited_combines != set(combine_nodes):
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved regional combine graph contains unused nodes.",
        )
    area_edges = {(node_id, 0) for node_id in area_nodes}
    leaf_edges = Counter(leaves)
    for edge in area_edges:
        if leaf_edges[edge] != 1:
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved regional combine graph omits an area.",
            )
        del leaf_edges[edge]
    if sum(leaf_edges.values()) != 1:
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved regional combine graph has unexpected leaves.",
        )
    positive_edge = next(iter(leaf_edges))
    positive_node = graph[positive_edge[0]]
    if (
        positive_node.get("class_type") != "CLIPTextEncode"
        or positive_node.get("inputs", {}).get("text") != positive_prompt
    ):
        raise ConflictError(
            "workflow_parameter_mismatch",
            "Resolved ComfyUI positive prompt does not match confirmation.",
        )


def _conditioning_leaves(
    edge: object,
    graph: dict[str, object],
    combine_nodes: dict[str, dict[str, object]],
    visited: set[str],
) -> list[tuple[str, int]]:
    if not _exact_edge(edge):
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved regional conditioning edge is invalid.",
        )
    node_id = edge[0]
    if node_id not in combine_nodes:
        return [(node_id, 0)]
    if node_id in visited:
        raise ValidationError(
            "unsafe_comfy_workflow",
            "Resolved regional combine graph contains a cycle.",
        )
    visited.add(node_id)
    inputs = combine_nodes[node_id]
    return _conditioning_leaves(
        inputs.get("conditioning_1"),
        graph,
        combine_nodes,
        visited,
    ) + _conditioning_leaves(
        inputs.get("conditioning_2"),
        graph,
        combine_nodes,
        visited,
    )


def _exact_edge(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and value[1] == 0
    )


def _validate_node_edges(
    node_id: str,
    inputs: dict[str, object],
    graph: dict[str, object],
) -> None:
    for item in inputs.values():
        if isinstance(item, list) and (
            len(item) != 2
            or not isinstance(item[0], str)
            or item[0] not in graph
            or type(item[1]) is not int
            or item[1] < 0
        ):
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved ComfyUI graph contains an invalid edge.",
                {"node_id": node_id},
            )
        if isinstance(item, dict) or item is None:
            raise ValidationError(
                "unsafe_comfy_workflow",
                "Resolved ComfyUI graph contains an invalid input value.",
                {"node_id": node_id},
            )


def _nested_version(stats: dict[str, object]) -> str | None:
    system = stats.get("system")
    candidates = (
        system.get("comfyui_version") if isinstance(system, dict) else None,
        system.get("version") if isinstance(system, dict) else None,
        stats.get("version"),
    )
    for value in candidates:
        if value is not None:
            if not isinstance(value, str):
                raise ArtifactError(
                    "invalid_backend_response",
                    "ComfyUI version must be a string or null.",
                )
            return value
    return None


def _loader_choices(value: object, loader_class: str, input_name: str) -> list[str]:
    try:
        choices = value[loader_class]["input"]["required"][input_name][0]
    except (KeyError, IndexError, TypeError) as error:
        raise ArtifactError(
            "invalid_backend_response",
            "ComfyUI model loader choices are missing.",
        ) from error
    if (
        not isinstance(choices, list)
        or any(not isinstance(item, str) or not _safe_relative_path(item) for item in choices)
        or len(set(choices)) != len(choices)
    ):
        raise ArtifactError(
            "invalid_backend_response",
            "ComfyUI model loader choices are invalid.",
        )
    return list(choices)


def _require_job_id(value: object) -> str:
    if (
        not isinstance(value, dict)
        or value.get("node_errors") not in ({}, None)
        or not isinstance(value.get("prompt_id"), str)
    ):
        raise StateError(
            "comfyui_submission_rejected",
            "ComfyUI rejected the workflow before assigning a job.",
        )
    return _validate_job_id(value["prompt_id"])


def _validate_job_id(value: object) -> str:
    if not isinstance(value, str) or JOB_ID_PATTERN.fullmatch(value) is None:
        raise ValidationError("invalid_comfyui_job_id", "ComfyUI job ID is invalid.")
    return value


def _history_state(history: dict[str, object], job_id: str) -> str:
    entry = history.get(job_id)
    if entry is None:
        return "absent"
    status = entry.get("status")
    if status is not None and not isinstance(status, dict):
        raise ArtifactError(
            "invalid_backend_response",
            "ComfyUI job status must be an object.",
        )
    status_name = status.get("status_str") if isinstance(status, dict) else None
    if status_name in {"error", "failed"}:
        return "rejected"
    if status_name in {"canceled", "cancelled"}:
        return "canceled"
    if isinstance(entry.get("outputs"), dict):
        return "completed"
    if isinstance(status, dict) and status.get("completed") is True:
        raise ArtifactError(
            "invalid_comfyui_output",
            "Completed ComfyUI job has no output object.",
        )
    return "running"


def _queue_job_ids(value: object, label: str) -> set[str]:
    if not isinstance(value, list):
        raise ArtifactError(
            "invalid_backend_response",
            f"ComfyUI {label} queue must be an array.",
        )
    result: set[str] = set()
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) < 2
            or not isinstance(item[1], str)
            or JOB_ID_PATTERN.fullmatch(item[1]) is None
        ):
            raise ArtifactError(
                "invalid_backend_response",
                f"ComfyUI {label} queue entry is invalid.",
            )
        result.add(item[1])
    return result


def _owned_output(
    history: dict[str, object],
    job_id: str,
    output_node: str,
) -> dict[str, str]:
    outputs = _history_outputs(history, job_id)
    if set(outputs) != {output_node}:
        raise ArtifactError(
            "invalid_comfyui_output",
            "ComfyUI returned an unexpected output node.",
            {"job_id": job_id},
        )
    return _one_owned_png(outputs[output_node], job_id)


def _owned_outputs(
    history: dict[str, object],
    job_id: str,
    roles: dict[str, str],
) -> dict[str, dict[str, str]]:
    if set(roles) != {"base", "mask", "final"} or len(set(roles.values())) != 3:
        raise ArtifactError(
            "invalid_comfyui_output",
            "Two-stage output roles are invalid.",
        )
    outputs = _history_outputs(history, job_id)
    if set(outputs) != set(roles.values()):
        raise ArtifactError(
            "invalid_comfyui_output",
            "ComfyUI returned unexpected output nodes.",
        )
    return {
        role: _one_owned_png(outputs[node_id], job_id)
        for role, node_id in roles.items()
    }


def _history_outputs(
    history: dict[str, object],
    job_id: str,
) -> dict[str, object]:
    try:
        outputs = history[job_id]["outputs"]
        if not isinstance(outputs, dict):
            raise TypeError("wrong output object")
        return outputs
    except (KeyError, TypeError) as error:
        raise ArtifactError(
            "invalid_comfyui_output",
            "ComfyUI did not return owned outputs for the completed job.",
            {"job_id": job_id},
        ) from error


def _one_owned_png(value: object, job_id: str) -> dict[str, str]:
    try:
        images = value["images"]
        if not isinstance(images, list) or len(images) != 1:
            raise TypeError("wrong image count")
        output = images[0]
        filename = output["filename"]
        subfolder = output["subfolder"]
        output_type = output["type"]
    except (KeyError, IndexError, TypeError) as error:
        raise ArtifactError(
            "invalid_comfyui_output",
            "ComfyUI did not return one image from the confirmed output node.",
            {"job_id": job_id},
        ) from error
    if (
        not isinstance(filename, str)
        or not filename.lower().endswith(".png")
        or not _safe_filename(filename)
        or not isinstance(subfolder, str)
        or not _safe_subfolder(subfolder)
        or output_type != "output"
    ):
        raise ArtifactError(
            "invalid_comfyui_output",
            "ComfyUI output metadata contains an unsafe path or type.",
            {"job_id": job_id},
        )
    return {"filename": filename, "subfolder": subfolder, "type": output_type}


def _view_path(output: dict[str, str]) -> str:
    return "/view?" + urllib.parse.urlencode((
        ("filename", output["filename"]),
        ("subfolder", output["subfolder"]),
        ("type", output["type"]),
    ))


def _write_validated_png(path: Path, data: bytes) -> None:
    if len(data) < 24 or data[:8] != PNG_SIGNATURE:
        raise ArtifactError(
            "invalid_backend_response",
            "ComfyUI returned malformed PNG data.",
        )
    width, height = struct.unpack(">II", data[16:24])
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".comfyui-",
        suffix=".png.tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        validate_png(temp_path, width, height)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _safe_filename(value: str) -> bool:
    return (
        value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and not PureWindowsPath(value).drive
    )


def _safe_subfolder(value: str) -> bool:
    if value == "":
        return True
    return "\\" not in value and _safe_relative_path(value)


def _safe_relative_path(value: str) -> bool:
    if not value or "\x00" in value:
        return False
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value.replace("\\", "/"))
    return (
        not windows.is_absolute()
        and not windows.drive
        and not posix.is_absolute()
        and all(part not in {"", ".", ".."} for part in posix.parts)
    )


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
