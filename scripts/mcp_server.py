#!/usr/bin/env python
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from local_gpu_imagegen.errors import AssetEngineError
from local_gpu_imagegen.model_identity import identity_token
from local_gpu_imagegen.postprocess import SUPPORTED_MODELS


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PYTHON = sys.executable
DEFAULT_COMMAND_TIMEOUT_SECONDS = int(os.environ.get("LOCAL_GPU_IMAGEGEN_COMMAND_TIMEOUT_SECONDS", "900"))
MAX_PREVIEW_BASE64_CHARS = 4 * ((1024 * 1024 + 2) // 3)
SERVER_VERSION = "0.5.0"
_asset_engine: Any | None = None
_runtime_services: Any | None = None


def send(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def text_content(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


def tool_error(
    code: str,
    category: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "category": category,
        "message": message,
    }
    if details:
        error["details"] = details
    return {
        "content": text_content(message),
        "structuredContent": {"error": error},
        "isError": True,
    }


def jsonrpc_error(
    request_id: object,
    code: int,
    message: str,
    category: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"category": category}
    if details:
        data["details"] = details
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message, "data": data},
    }


def command_error(
    script: str,
    return_code: int,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    diagnostic = stderr.strip() or stdout.strip() or f"{script} exited without an error message."
    if return_code == 124:
        return tool_error(
            "command_timeout",
            "timeout",
            diagnostic,
            {"script": script, "timeoutSeconds": DEFAULT_COMMAND_TIMEOUT_SECONDS},
        )
    return tool_error(
        "backend_command_failed",
        "execution",
        diagnostic,
        {"script": script, "exitCode": return_code},
    )


def tool_success(data: dict[str, Any], preview: dict[str, str] | None = None) -> dict[str, Any]:
    content: list[dict[str, str]] = text_content(json.dumps(data, indent=2))
    if preview:
        content.append({"type": "image", "data": preview["data"], "mimeType": preview["mimeType"]})
    return {
        "content": content,
        "structuredContent": data,
        "isError": False,
    }


def script_json_result(
    script: str,
    return_code: int,
    stdout: str,
    stderr: str,
    accepted_return_codes: set[int] | None = None,
) -> dict[str, Any]:
    accepted = accepted_return_codes or {0}
    if return_code not in accepted:
        return command_error(script, return_code, stdout, stderr)
    if not stdout.strip():
        return command_error(script, return_code, stdout, stderr)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return tool_error(
            "invalid_backend_response",
            "execution",
            f"{script} did not return a valid JSON object.",
            {"script": script, "exitCode": return_code},
        )
    if not isinstance(data, dict):
        return tool_error(
            "invalid_backend_response",
            "execution",
            f"{script} returned JSON, but the top-level value was not an object.",
            {"script": script, "exitCode": return_code},
        )
    return tool_success(data)


def run_script(script: str, args: list[str] | None = None) -> tuple[int, str, str]:
    command = [PYTHON, str(SCRIPTS / script)]
    if args:
        command.extend(args)
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            cwd=str(ROOT),
            timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"{script} exceeded the {DEFAULT_COMMAND_TIMEOUT_SECONDS}s timeout."


def get_capabilities() -> dict[str, object]:
    code, stdout, _stderr = run_script("check_gpu.py", [])
    if code != 0:
        return {
            "ready": False,
            "backends": {},
            "warnings": ["capability_check_failed"],
        }
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "ready": False,
            "backends": {},
            "warnings": ["capability_check_invalid_json"],
        }
    if not isinstance(value, dict):
        return {
            "ready": False,
            "backends": {},
            "warnings": ["capability_check_invalid_result"],
        }
    available_backends = []
    if value.get("webui_ready") is True:
        available_backends.append("webui")
    if value.get("diffusers_ready") is True:
        available_backends.append("diffusers")
    if value.get("comfyui_ready") is True:
        available_backends.append("comfyui")
    return {**value, "available_backends": available_backends}


def _diffusers_runner(request: dict[str, object]) -> dict[str, object]:
    model = request.get("model")
    if not isinstance(model, dict):
        raise AssetEngineError("invalid_backend_request", "Diffusers model identity is missing.", "validation")
    args = [
        "--prompt", str(request["positive_prompt"]),
        "--negative-prompt", str(request["negative_prompt"]),
        "--backend", "diffusers",
        "--mode", str(request["mode"]),
        "--model", str(model["backend_model_id"]),
        "--width", str(request["width"]),
        "--height", str(request["height"]),
        "--steps", str(request["steps"]),
        "--guidance-scale", str(request["guidance_scale"]),
        "--seed", str(request["seed"]),
        "--output-dir", str(Path(str(request["output_path"])).parent),
        "--filename", Path(str(request["output_path"])).name,
    ]
    for field, flag in (
        ("source_path", "--input-image"),
        ("mask_path", "--mask-image"),
        ("strength", "--strength"),
    ):
        if request.get(field) is not None:
            args.extend((flag, str(request[field])))
    code, stdout, stderr = run_script("generate_image.py", args)
    if code != 0:
        raise AssetEngineError(
            "backend_command_failed",
            "Diffusers compatibility backend failed.",
            "backend",
            {"exit_code": code, "stderr": stderr},
        )
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise AssetEngineError(
            "invalid_backend_result",
            "Diffusers compatibility backend returned invalid JSON.",
            "artifact",
        ) from error
    if not isinstance(value, dict):
        raise AssetEngineError("invalid_backend_result", "Diffusers result must be an object.", "artifact")
    return {
        **value,
        "backend": "diffusers",
        "model": model["backend_model_id"],
        "endpoint_identity": model["endpoint_identity"],
        "model_identity_token": model["identity_token"],
        "identity_strength": model["identity_strength"],
        "workflow_template_id": None,
        "workflow_template_version": None,
        "prompt_compiler_id": request["prompt_compiler_id"],
        "prompt_compiler_version": request["prompt_compiler_version"],
    }


def get_runtime_services() -> Any:
    global _asset_engine, _runtime_services
    if _runtime_services is None:
        from local_gpu_imagegen.services import build_services
        from local_gpu_imagegen.trust_registry import default_state_dir

        _runtime_services = build_services(
            ROOT,
            Path(os.environ.get("LOCAL_GPU_IMAGEGEN_OUTPUT_DIR", ROOT / "outputs")),
            default_state_dir(),
            get_capabilities,
            _diffusers_runner,
        )
        _asset_engine = _runtime_services.engine
    return _runtime_services


def get_asset_engine() -> Any:
    return get_runtime_services().engine


def _object_schema(
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _output_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    common = {
        "ok": {"type": "boolean"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    }
    success = _object_schema({**common, **properties}, ["ok", *required, "warnings"])
    error_value = _object_schema(
        {
            "code": {"type": "string"},
            "category": {"type": "string"},
            "message": {"type": "string"},
            "details": {"type": "object", "additionalProperties": True},
        },
        ["code", "category", "message"],
    )
    error = _object_schema({"error": error_value}, ["error"])
    return {"oneOf": [success, error]}


def tool_schema() -> list[dict[str, Any]]:
    tools = [
        {
            "name": "local_gpu_imagegen_check",
            "description": "Check Python packages and CUDA readiness for local GPU image generation.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "required": ["ready"],
                "properties": {
                    "ready": {"type": "boolean"},
                    "diffusers_ready": {"type": "boolean"},
                    "webui_ready": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
        },
        {
            "name": "local_gpu_generate_image",
            "description": "Generate or transform an image using local Stable Diffusion through WebUI or diffusers on the local GPU.",
            "inputSchema": {
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                    "model": {"type": "string"},
                    "backend": {"type": "string", "enum": ["auto", "webui", "diffusers"]},
                    "mode": {"type": "string", "enum": ["txt2img", "img2img", "inpaint"]},
                    "webui_url": {"type": "string"},
                    "sampler_name": {"type": "string"},
                    "scheduler": {"type": "string", "enum": ["default", "dpmpp", "euler", "euler-a", "ddim", "unipc", "lcm"]},
                    "input_image": {"type": "string"},
                    "mask_image": {"type": "string"},
                    "strength": {"type": "number", "minimum": 0, "maximum": 1},
                    "lora": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "lora_scale": {"type": "number", "minimum": 0, "maximum": 2},
                    "cpu_offload": {"type": "boolean"},
                    "vae_tiling": {"type": "boolean"},
                    "disable_safety_checker": {"type": "boolean"},
                    "width": {"type": "integer", "minimum": 256, "maximum": 1536},
                    "height": {"type": "integer", "minimum": 256, "maximum": 1536},
                    "steps": {"type": "integer", "minimum": 1, "maximum": 80},
                    "guidance_scale": {"type": "number", "minimum": 0, "maximum": 20},
                    "seed": {"type": "integer"},
                    "output_dir": {"type": "string"},
                    "filename": {"type": "string"},
                    "allow_cpu": {"type": "boolean"},
                    "allow_download": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "required": ["ok", "path", "backend", "mode"],
                "properties": {
                    "ok": {"type": "boolean"},
                    "path": {"type": "string"},
                    "backend": {"type": "string", "enum": ["webui", "diffusers"]},
                    "mode": {"type": "string", "enum": ["txt2img", "img2img", "inpaint"]},
                },
                "additionalProperties": True,
            },
        },
    ]
    json_object = {"type": "object", "additionalProperties": True}
    json_value = {"type": ["object", "array", "string", "number", "boolean", "null"]}
    json_array = {"type": "array", "items": json_value}
    preserve_item = _object_schema({
        "target": {"type": "string", "minLength": 1},
        "strength": {"type": "string", "enum": ["hard", "soft"]},
    }, ["target", "strength"])
    revision_contract = _object_schema({
        "preserve": {"type": "array", "items": preserve_item},
        "change": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    }, ["preserve", "change"])
    point = _object_schema({
        "x": {"type": "number", "minimum": 0, "maximum": 1},
        "y": {"type": "number", "minimum": 0, "maximum": 1},
    }, ["x", "y"])
    geometry_item = _object_schema({
        "type": {"type": "string", "enum": ["rectangle", "polygon"]},
        "x": {"type": "number", "minimum": 0, "maximum": 1},
        "y": {"type": "number", "minimum": 0, "maximum": 1},
        "width": {"type": "number", "minimum": 0, "maximum": 1},
        "height": {"type": "number", "minimum": 0, "maximum": 1},
        "points": {"type": "array", "minItems": 3, "items": point},
    }, ["type"])
    run_manifest_properties = {
        "run_id": {"type": "string"},
        "schema_version": {"type": "integer"},
        "manifest_revision": {"type": "integer"},
        "state": {"type": "string"},
        "last_stable_state": {"type": "string"},
        "active_attempt": json_value,
        "parent": json_value,
        "revision": json_value,
        "request": json_object,
        "attempts": json_array,
        "rounds": json_array,
        "reviews": json_array,
        "masks": json_array,
        "final": json_value,
        "recoverable_next_actions": {"type": "array", "items": {"type": "string"}},
    }
    tools.extend([
        {
            "name": "local_gpu_discover_models",
            "description": "Plan or execute bounded local model discovery without loading model weights.",
            "inputSchema": _object_schema({
                "phase": {"type": "string", "enum": ["plan", "execute"]},
                "mode": {"type": "string", "enum": ["api_only", "selected_folders", "common_locations", "full_drive"]},
                "stage": {"type": "string", "enum": ["index", "fingerprint"]},
                "backends": {"type": "array", "items": {"type": "string", "enum": ["webui", "comfyui"]}},
                "roots": {"type": "array", "items": {"type": "string"}},
                "explicit_includes": {"type": "array", "items": {"type": "string"}},
                "plan_id": {"type": "string", "minLength": 1},
                "confirmation": {"type": "string", "minLength": 1},
                "network_confirmation": {"type": "string", "minLength": 1},
                "selected_candidates": {"type": "array", "items": {"type": "string"}},
            }, ["phase"]),
            "outputSchema": _output_schema({
                "plan_id": {"type": "string"},
                "scope_hash": {"type": "string"},
                "expires_at": {"type": "number"},
                "confirmation": {"type": "string"},
                "network_confirmation": {"type": "string"},
                "incomplete": {"type": "boolean"},
                "candidates": json_array,
                "trusted": {"type": "boolean"},
            }, []),
        },
        {
            "name": "local_gpu_set_model_trust",
            "description": "Approve or revoke one exact current local model identity after explicit confirmation.",
            "inputSchema": _object_schema({
                "action": {"type": "string", "enum": ["approve_private", "approve_public_candidate", "revoke"]},
                "identity_token": {"type": "string", "minLength": 1},
                "confirmation": {"type": "string", "minLength": 1},
                "capabilities": json_object,
                "public_metadata": _object_schema({
                    "source": {"type": "string", "minLength": 1},
                    "license_id": {"type": "string", "minLength": 1},
                    "license_url": {"type": "string", "minLength": 1},
                    "output_redistribution_status": {"type": "string", "minLength": 1},
                }, ["source", "license_id", "license_url", "output_redistribution_status"]),
                "workflow_path": {"type": "string", "minLength": 1},
                "workflow_binding": json_object,
                "preference": {"type": "integer", "minimum": -100, "maximum": 100},
            }, ["action", "identity_token", "confirmation"]),
            "outputSchema": _output_schema({
                "catalog_id": {"type": "string"},
                "identity_token": {"type": "string"},
                "identity_strength": {"type": "string"},
                "scope": {"type": "string"},
                "revoked": {"type": "boolean"},
                "registered_workflow": json_object,
            }, ["identity_token"]),
        },
        {
            "name": "local_gpu_recommend_models",
            "description": "Recommend one exact confirmed-capability route and at most two alternatives.",
            "inputSchema": _object_schema({
                "authorization_scope": {"type": "string", "enum": ["private", "public_evidence"]},
                "operation": {"type": "string", "enum": ["txt2img", "img2img", "inpaint"]},
                "profile": {"type": "string", "enum": _registered_profile_ids()},
                "style": {"type": ["string", "null"], "enum": [None, *_registered_style_ids()]},
                "width": {"type": "integer", "minimum": 256, "maximum": 1536},
                "height": {"type": "integer", "minimum": 256, "maximum": 1536},
                "affinity_tags": {"type": "array", "items": {"type": "string"}},
                "required_vram_gb": {"type": ["number", "null"]},
                "preferred_model_id": {"type": ["string", "null"]},
            }, [
                "authorization_scope", "operation", "profile", "style", "width", "height",
                "affinity_tags", "required_vram_gb", "preferred_model_id",
            ]),
            "outputSchema": _output_schema({
                "requirements": json_object,
                "routes": json_array,
                "reason": {"type": ["string", "null"]},
            }, ["requirements", "routes", "reason"]),
        },
        {
            "name": "local_gpu_list_profiles",
            "description": "List registered visual-asset profiles and current local backend capabilities.",
            "inputSchema": _object_schema({
                "authorization_scope": {"type": "string", "enum": ["private", "public_evidence"]},
            }, []),
            "outputSchema": _output_schema({
                "profiles": json_object,
                "styles": json_object,
                "models": json_object,
                "capabilities": json_object,
            }, ["profiles", "styles", "models", "capabilities"]),
        },
        {
            "name": "local_gpu_start_run",
            "description": "Create a confirmed visual-asset run.",
            "inputSchema": _object_schema({
                "intent": {"type": "string", "minLength": 1},
                "profile": {"type": "string", "enum": _registered_profile_ids()},
                "style": {"type": ["string", "null"], "enum": [None, *_registered_style_ids()]},
                "constraints": json_object,
                "model_choice": {"type": "string", "minLength": 1},
                "backend": {"type": "string", "enum": ["webui", "diffusers", "comfyui"]},
                "authorization_scope": {"type": "string", "enum": ["private", "public_evidence"]},
                "route_token": {"type": "string", "minLength": 1},
                "max_rounds": {"type": "integer", "minimum": 1, "maximum": 3},
                "upscale_policy": {"type": "string", "enum": ["auto", "off"]},
            }, [
                "intent", "profile", "style", "constraints", "model_choice", "backend",
                "authorization_scope", "route_token", "max_rounds", "upscale_policy",
            ]),
            "outputSchema": _output_schema({
                "run_id": {"type": "string"},
                "state": {"type": "string"},
                "max_rounds": {"type": "integer"},
                "merged_rubric": json_object,
            }, ["run_id", "state", "max_rounds", "merged_rubric"]),
        },
        {
            "name": "local_gpu_get_run",
            "description": "Get the current persisted state of a visual-asset run.",
            "inputSchema": _object_schema({"run_id": {"type": "string", "minLength": 1}}, ["run_id"]),
            "outputSchema": _output_schema(run_manifest_properties, ["run_id", "state", "rounds", "recoverable_next_actions"]),
        },
        {
            "name": "local_gpu_branch_run",
            "description": "Create an immutable child revision run from one reviewed parent round.",
            "inputSchema": _object_schema({
                "parent_run_id": {"type": "string", "minLength": 1},
                "parent_round": {"type": "integer", "minimum": 1, "maximum": 3},
                "contract": revision_contract,
                "max_rounds": {"type": "integer", "minimum": 1, "maximum": 3},
                "edit_mode": {"type": "string", "enum": ["prompt-refine", "img2img", "inpaint"]},
                "denoising_strength": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
            }, ["parent_run_id", "parent_round", "contract", "max_rounds", "edit_mode"]),
            "outputSchema": _output_schema(
                run_manifest_properties,
                ["run_id", "state", "parent", "revision"],
            ),
        },
        {
            "name": "local_gpu_prepare_mask",
            "description": "Prepare an unconfirmed child-run inpaint mask and return its JPEG overlay.",
            "inputSchema": _object_schema({
                "run_id": {"type": "string", "minLength": 1},
                "user_mask_path": {"type": "string", "minLength": 1},
                "geometry": {"type": "array", "minItems": 1, "items": geometry_item},
                "feather_pixels": {"type": "integer", "minimum": 0, "maximum": 64},
            }, ["run_id"]),
            "outputSchema": _output_schema({
                "mask_id": {"type": "string"},
                "source": {"type": "string", "enum": ["geometry", "user"]},
                "source_image_sha256": {"type": "string"},
                "mask_sha256": {"type": "string"},
                "geometry": json_value,
                "feather_pixels": {"type": "integer"},
                "mask_path": {"type": "string"},
                "overlay_path": {"type": "string"},
                "confirmed": {"type": "boolean"},
                "confirmed_at": json_value,
            }, ["mask_id", "mask_path", "overlay_path", "confirmed"]),
        },
        {
            "name": "local_gpu_confirm_mask",
            "description": "Confirm an unchanged prepared mask after explicit overlay approval.",
            "inputSchema": _object_schema({
                "run_id": {"type": "string", "minLength": 1},
                "mask_id": {"type": "string", "minLength": 1},
            }, ["run_id", "mask_id"]),
            "outputSchema": _output_schema({
                "mask_id": {"type": "string"},
                "source": {"type": "string", "enum": ["geometry", "user"]},
                "source_image_sha256": {"type": "string"},
                "mask_sha256": {"type": "string"},
                "geometry": json_value,
                "feather_pixels": {"type": "integer"},
                "mask_path": {"type": "string"},
                "overlay_path": {"type": "string"},
                "confirmed": {"type": "boolean"},
                "confirmed_at": json_value,
            }, ["mask_id", "mask_path", "overlay_path", "confirmed"]),
        },
        {
            "name": "local_gpu_generate_round",
            "description": "Generate one root or immutable revision round and return an optional bounded JPEG preview.",
            "inputSchema": _object_schema({
                "run_id": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
                "action": {"type": "string", "enum": ["initial", "refine", "explore"]},
                "edit_mode": {"type": "string", "enum": ["txt2img", "img2img", "inpaint"]},
                "mask_id": {"type": "string", "minLength": 1},
                "plan": json_object,
                "seed": {"type": "integer"},
                "change_summary": {"type": "string", "minLength": 1},
            }, ["run_id", "idempotency_key", "action", "edit_mode", "plan", "seed", "change_summary"]),
            "outputSchema": _output_schema({
                "run_id": {"type": "string"},
                "state": {"type": "string"},
                "round": json_object,
                "full_image_path": {"type": "string"},
                "recoverable_next_actions": {"type": "array", "items": {"type": "string"}},
            }, ["run_id", "state", "round", "full_image_path"]),
        },
        {
            "name": "local_gpu_record_review",
            "description": "Record human or model review evidence for one generated round.",
            "inputSchema": _object_schema({
                "run_id": {"type": "string", "minLength": 1},
                "round_number": {"type": "integer", "minimum": 1, "maximum": 3},
                "scores": json_object,
                "hard_failures": {"type": "array", "items": {"type": "string"}},
                "critique": {"type": "string", "minLength": 1},
                "constraint_results": json_object,
                "preservation_results": {"type": "array", "items": json_object},
                "next_action": {"type": "string", "enum": ["refine", "explore", "finalize"]},
            }, ["run_id", "round_number", "scores", "hard_failures", "critique", "constraint_results", "next_action"]),
            "outputSchema": _output_schema(run_manifest_properties, ["run_id", "state", "rounds", "reviews", "recoverable_next_actions"]),
        },
        {
            "name": "local_gpu_finalize_run",
            "description": "Publish the selected reviewed round as the run's final PNG.",
            "inputSchema": _object_schema({
                "run_id": {"type": "string", "minLength": 1},
                "round_number": {"type": "integer", "minimum": 1, "maximum": 3},
                "summary": {"type": "string", "minLength": 1},
                "postprocess": _object_schema({
                    "type": {"type": "string", "enum": ["anime_upscale"]},
                    "model": {"type": "string", "enum": sorted(SUPPORTED_MODELS)},
                }, ["type", "model"]),
            }, ["run_id", "round_number", "summary"]),
            "outputSchema": _output_schema({
                **run_manifest_properties,
                "max_rounds": {"type": ["integer", "null"]},
                "full_image_path": {"type": "string"},
            }, ["run_id", "state", "final", "full_image_path", "recoverable_next_actions"]),
        },
        {
            "name": "local_gpu_cleanup_run",
            "description": "Remove run intermediates or a fully confirmed run directory.",
            "inputSchema": _object_schema({
                "run_id": {"type": "string", "minLength": 1},
                "scope": {"type": "string", "enum": ["intermediates", "all"]},
                "confirmation": {"type": "string"},
            }, ["run_id", "scope", "confirmation"]),
            "outputSchema": _output_schema({
                "run_id": {"type": "string"},
                "scope": {"type": "string", "enum": ["intermediates", "all"]},
            }, ["run_id", "scope"]),
        },
    ])
    return tools


def _registered_profile_ids() -> list[str]:
    return sorted(path.stem for path in (ROOT / "profiles" / "use-cases").glob("*.json"))


def _registered_style_ids() -> list[str]:
    return sorted(path.stem for path in (ROOT / "profiles" / "styles").glob("*.json"))



def _approved_model_ids() -> list[str]:
    from local_gpu_imagegen.profile_registry import ProfileRegistry

    models = ProfileRegistry(ROOT / "profiles").list_catalog()["models"]
    return sorted(
        model_id
        for model_id, model in models.items()
        if model.get("enabled") is True and model.get("license_status") == "approved"
    )


def schema_type_matches(value: object, schema_type: object) -> bool:
    if isinstance(schema_type, list):
        return any(schema_type_matches(value, candidate) for candidate in schema_type)
    if schema_type == "null":
        return value is None
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "boolean":
        return type(value) is bool
    if schema_type == "integer":
        return type(value) is int
    if schema_type == "number":
        return type(value) in (int, float) and math.isfinite(value)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    return False


def _validate_nested_object(field: str, value: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any] | None:
    properties = schema.get("properties", {})
    unknown = sorted(set(value) - set(properties))
    if unknown:
        fields = [f"{field}.{name}" for name in unknown]
        return tool_error(
            "unknown_argument",
            "validation",
            f"Unknown nested tool argument(s): {', '.join(fields)}.",
            {"fields": fields},
        )
    for name in schema.get("required", []):
        if name not in value:
            nested_field = f"{field}.{name}"
            return tool_error(
                "missing_argument",
                "validation",
                f"postprocess requires {name}.",
                {"field": nested_field},
            )
    for name, nested_value in value.items():
        nested_schema = properties[name]
        expected_type = nested_schema.get("type")
        nested_field = f"{field}.{name}"
        if expected_type and not schema_type_matches(nested_value, expected_type):
            return tool_error(
                "invalid_argument_type",
                "validation",
                f"{nested_field} must be a JSON {expected_type}.",
                {"field": nested_field, "expectedType": expected_type},
            )
        if "enum" in nested_schema and nested_value not in nested_schema["enum"]:
            return tool_error(
                "invalid_argument_value",
                "validation",
                f"{nested_field} is not supported.",
                {"field": nested_field, "allowed": nested_schema["enum"]},
            )
    return None


def validate_tool_arguments(tool: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any] | None:
    schema = tool["inputSchema"]
    properties = schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        return tool_error(
            "unknown_argument",
            "validation",
            f"Unknown tool argument(s): {', '.join(unknown)}.",
            {"fields": unknown},
        )

    for field in schema.get("required", []):
        if field not in arguments:
            tool_name = tool["name"]
            message = (
                "local_gpu_generate_image requires a non-empty prompt."
                if field == "prompt"
                else f"{tool_name} requires {field}."
            )
            return tool_error(
                "invalid_prompt" if field == "prompt" else "missing_argument",
                "validation",
                message,
                {"field": field},
            )

    for field, value in arguments.items():
        field_schema = properties[field]
        expected_type = field_schema.get("type")
        if expected_type and not schema_type_matches(value, expected_type):
            code = "invalid_lora" if field == "lora" else "invalid_argument_type"
            type_name = " or ".join(expected_type) if isinstance(expected_type, list) else expected_type
            message = "lora must be an array of strings." if field == "lora" else f"{field} must be a JSON {type_name}."
            return tool_error(code, "validation", message, {"field": field, "expectedType": expected_type})
        if "enum" in field_schema and value not in field_schema["enum"]:
            allowed_text = ", ".join("null" if item is None else str(item) for item in field_schema["enum"])
            return tool_error(
                "invalid_argument_value",
                "validation",
                f"{field} must be one of: {allowed_text}.",
                {"field": field, "allowed": field_schema["enum"]},
            )
        if expected_type in ("integer", "number"):
            if "exclusiveMinimum" in field_schema and value <= field_schema["exclusiveMinimum"]:
                return tool_error(
                    "invalid_argument_value",
                    "validation",
                    f"{field} must be greater than {field_schema['exclusiveMinimum']}.",
                    {"field": field, "exclusiveMinimum": field_schema["exclusiveMinimum"]},
                )
            if "minimum" in field_schema and value < field_schema["minimum"]:
                return tool_error(
                    "invalid_argument_value",
                    "validation",
                    f"{field} must be at least {field_schema['minimum']}.",
                    {"field": field, "minimum": field_schema["minimum"]},
                )
            if "maximum" in field_schema and value > field_schema["maximum"]:
                return tool_error(
                    "invalid_argument_value",
                    "validation",
                    f"{field} must be at most {field_schema['maximum']}.",
                    {"field": field, "maximum": field_schema["maximum"]},
                )
        if "const" in field_schema and value != field_schema["const"]:
            return tool_error(
                "invalid_argument_value",
                "validation",
                f"{field} must equal {field_schema['const']}.",
                {"field": field, "expected": field_schema["const"]},
            )
        if expected_type == "string" and "minLength" in field_schema and len(value.strip()) < field_schema["minLength"]:
            return tool_error(
                "invalid_argument_value",
                "validation",
                f"{field} must be a non-empty string.",
                {"field": field},
            )
        if expected_type == "array" and "items" in field_schema:
            if "minItems" in field_schema and len(value) < field_schema["minItems"]:
                return tool_error(
                    "invalid_argument_value",
                    "validation",
                    f"{field} must contain at least {field_schema['minItems']} item(s).",
                    {"field": field, "minItems": field_schema["minItems"]},
                )
            item_type = field_schema["items"].get("type")
            if item_type and not all(schema_type_matches(item, item_type) for item in value):
                return tool_error(
                    "invalid_lora" if field == "lora" else "invalid_argument_type",
                    "validation",
                    f"{field} must be an array of {item_type}s.",
                    {"field": field, "itemType": item_type},
                )

    if tool["name"] == "local_gpu_finalize_run" and "postprocess" in arguments:
        postprocess = arguments["postprocess"]
        assert isinstance(postprocess, dict)
        nested_error = _validate_nested_object("postprocess", postprocess, properties["postprocess"])
        if nested_error is not None:
            return nested_error

    if tool["name"] == "local_gpu_discover_models":
        phase = arguments.get("phase")
        if phase == "plan":
            forbidden = sorted(set(arguments) & {"plan_id", "confirmation", "network_confirmation"})
            if forbidden:
                return tool_error(
                    "invalid_discovery_phase",
                    "validation",
                    "Discovery planning cannot include execution confirmation fields.",
                    {"fields": forbidden},
                )
        elif phase == "execute" and not {"plan_id", "confirmation"} <= set(arguments):
            return tool_error(
                "missing_argument",
                "validation",
                "Discovery execution requires plan_id and confirmation.",
                {"fields": ["plan_id", "confirmation"]},
            )

    if tool["name"] == "local_gpu_set_model_trust":
        action = arguments.get("action")
        if action in {"approve_private", "approve_public_candidate"} and "capabilities" not in arguments:
            return tool_error(
                "missing_argument",
                "validation",
                "Model approval requires declared capabilities.",
                {"field": "capabilities"},
            )
        if action == "approve_public_candidate" and "public_metadata" not in arguments:
            return tool_error(
                "missing_argument",
                "validation",
                "Public candidate approval requires public_metadata.",
                {"field": "public_metadata"},
            )
        if ("workflow_path" in arguments) != ("workflow_binding" in arguments):
            return tool_error(
                "invalid_workflow_binding",
                "validation",
                "workflow_path and workflow_binding must be provided together.",
                {"fields": ["workflow_path", "workflow_binding"]},
            )

    if tool["name"] == "local_gpu_branch_run":
        edit_mode = arguments.get("edit_mode")
        has_strength = "denoising_strength" in arguments
        if edit_mode == "prompt-refine" and has_strength or edit_mode in {"img2img", "inpaint"} and not has_strength:
            return tool_error(
                "invalid_denoising_strength",
                "validation",
                "denoising_strength is required only for img2img and inpaint revisions.",
                {"field": "denoising_strength", "edit_mode": edit_mode},
            )

    if tool["name"] == "local_gpu_prepare_mask":
        has_user_mask = "user_mask_path" in arguments
        has_geometry = "geometry" in arguments
        if has_user_mask == has_geometry:
            return tool_error(
                "invalid_mask_source",
                "validation",
                "Provide exactly one of user_mask_path or geometry.",
                {"fields": ["user_mask_path", "geometry"]},
            )

    prompt = arguments.get("prompt")
    if "prompt" in properties and (not isinstance(prompt, str) or not prompt.strip()):
        return tool_error(
            "invalid_prompt",
            "validation",
            "local_gpu_generate_image requires a non-empty prompt.",
            {"field": "prompt"},
        )

    for field in ("width", "height"):
        if field in arguments and arguments[field] % 8 != 0:
            return tool_error(
                "invalid_dimensions",
                "validation",
                "width and height must be divisible by 8.",
                {"field": field},
            )

    mode = arguments.get("mode", "txt2img")
    if mode in ("img2img", "inpaint") and not arguments.get("input_image"):
        return tool_error(
            "invalid_mode_arguments",
            "validation",
            f"input_image is required for {mode} mode.",
            {"field": "input_image", "mode": mode},
        )
    if mode == "inpaint" and not arguments.get("mask_image"):
        return tool_error(
            "invalid_mode_arguments",
            "validation",
            "mask_image is required for inpaint mode.",
            {"field": "mask_image", "mode": mode},
        )
    if mode == "txt2img" and (arguments.get("input_image") or arguments.get("mask_image")):
        return tool_error(
            "invalid_mode_arguments",
            "validation",
            "input_image and mask_image are only valid for img2img/inpaint modes.",
            {"mode": mode},
        )
    if (
        tool["name"] == "local_gpu_cleanup_run"
        and arguments.get("scope") == "all"
        and arguments.get("confirmation") != arguments.get("run_id")
    ):
        return tool_error(
            "invalid_confirmation",
            "validation",
            "confirmation must exactly equal run_id when scope is all.",
            {"field": "confirmation"},
        )
    if tool["name"] == "local_gpu_generate_round":
        plan = arguments.get("plan")
        parameters = plan.get("parameters") if isinstance(plan, dict) else None
        nested_mode = parameters.get("mode") if isinstance(parameters, dict) else None
        if nested_mode is not None and nested_mode != arguments.get("edit_mode"):
            return tool_error(
                "edit_mode_mismatch",
                "validation",
                "Generation plan parameters.mode must match the authoritative edit_mode.",
                {"edit_mode": arguments.get("edit_mode"), "plan_mode": nested_mode},
            )
    return None


def _successful_engine_data(value: dict[str, Any]) -> dict[str, Any]:
    data = dict(value)
    data.setdefault("ok", True)
    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        data["warnings"] = []
    return data


def _preview_block(preview: object) -> dict[str, str] | None:
    data = getattr(preview, "data_base64", None)
    mime_type = getattr(preview, "mime_type", None)
    if (
        isinstance(data, str)
        and data
        and len(data) <= MAX_PREVIEW_BASE64_CHARS
        and mime_type == "image/jpeg"
    ):
        return {"data": data, "mimeType": "image/jpeg"}
    return None


def _asset_error(error: AssetEngineError) -> dict[str, Any]:
    result = tool_error(error.code, error.category, str(error.args[0]), dict(error.details))
    result["structuredContent"]["error"]["details"] = dict(error.details)
    return result


def _discovery_call(services: Any, arguments: dict[str, Any]) -> dict[str, object]:
    if arguments["phase"] == "plan":
        request = {
            field: arguments[field]
            for field in (
                "mode", "stage", "backends", "roots", "explicit_includes", "selected_candidates"
            )
            if field in arguments
        }
        return services.discovery.plan(request)
    return services.discovery.execute(
        arguments["plan_id"],
        arguments["confirmation"],
        network_confirmation=arguments.get("network_confirmation"),
    )


def _inventory_identity(services: Any, token: str) -> dict[str, object]:
    matches = []
    for record in services.discovery.inventory():
        if isinstance(record, dict) and identity_token(record) == token:
            matches.append(record)
    if len(matches) != 1:
        raise AssetEngineError(
            "model_identity_not_current",
            "Trust changes require one exact identity from the current inventory.",
            "validation",
        )
    return matches[0]


def _registered_workflow_binding(
    services: Any,
    record: dict[str, object],
    path: str,
    binding: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    inventory = services.discovery.inventory()
    comfy_records = [
        item for item in inventory
        if isinstance(item, dict) and item.get("backend") == "comfyui"
    ]
    available_models = sorted({
        str(item["backend_model_id"])
        for item in comfy_records
        if isinstance(item.get("backend_model_id"), str)
    })
    registered = services.workflows.register_import(Path(path), binding, available_models)
    graph = registered.get("graph")
    loader_names = [
        node.get("inputs", {}).get("ckpt_name")
        for node in graph.values()
        if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple"
    ] if isinstance(graph, dict) else []
    matches = [
        item for item in comfy_records
        if item.get("backend_model_id") in loader_names
    ]
    if record.get("backend") == "comfyui":
        matches = [item for item in matches if identity_token(item) == identity_token(record)]
    if len(matches) != 1:
        raise AssetEngineError(
            "workflow_model_binding_ambiguous",
            "Imported workflow must bind one exact current ComfyUI model identity.",
            "validation",
        )
    selected = matches[0]
    trust_binding = {
        "backend": "comfyui",
        "endpoint_identity": selected["endpoint_identity"],
        "backend_model_id": selected["backend_model_id"],
        "template_id": registered["template_id"],
        "template_version": registered["template_version"],
    }
    public_registration = {
        "template_id": registered["template_id"],
        "template_version": registered["template_version"],
        "workflow_sha256": registered["workflow_sha256"],
    }
    return trust_binding, public_registration


def _trust_call(services: Any, arguments: dict[str, Any]) -> dict[str, object]:
    token = arguments["identity_token"]
    if arguments["action"] == "revoke":
        catalog_id = "local:" + token.removeprefix("model:")[:24]
        return services.trust.revoke(catalog_id, token, arguments["confirmation"])

    record = _inventory_identity(services, token)
    workflow_binding = None
    registered_workflow = None
    if "workflow_path" in arguments:
        workflow_binding, registered_workflow = _registered_workflow_binding(
            services,
            record,
            arguments["workflow_path"],
            arguments["workflow_binding"],
        )
    preference = arguments.get("preference", 0)
    if arguments["action"] == "approve_private":
        approved = services.trust.approve_private(
            record,
            arguments["confirmation"],
            capabilities=arguments["capabilities"],
            workflow_binding=workflow_binding,
            preference=preference,
        )
    else:
        approved = services.trust.approve_public_candidate(
            record,
            arguments["confirmation"],
            metadata=arguments["public_metadata"],
            capabilities=arguments["capabilities"],
            workflow_binding=workflow_binding,
            preference=preference,
        )
    result = {
        field: approved[field]
        for field in ("catalog_id", "identity_token", "identity_strength", "scope")
    }
    if registered_workflow is not None:
        result["registered_workflow"] = registered_workflow
    return result


def handle_tool_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    tool = next((candidate for candidate in tool_schema() if candidate["name"] == name), None)
    if tool is None:
        return tool_error(
            "unknown_tool",
            "validation",
            f"Unknown tool: {name}",
            {"toolName": name},
        )

    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return tool_error(
            "invalid_arguments",
            "validation",
            "Tool arguments must be a JSON object.",
        )
    validation_error = validate_tool_arguments(tool, arguments)
    if validation_error:
        return validation_error

    if name == "local_gpu_imagegen_check":
        code, stdout, stderr = run_script("check_gpu.py")
        return script_json_result("check_gpu.py", code, stdout, stderr, {0, 1})

    if name == "local_gpu_generate_image":
        prompt = arguments.get("prompt")

        args = ["--prompt", prompt]
        mapping = {
            "negative_prompt": "--negative-prompt",
            "model": "--model",
            "backend": "--backend",
            "mode": "--mode",
            "webui_url": "--webui-url",
            "sampler_name": "--sampler-name",
            "scheduler": "--scheduler",
            "input_image": "--input-image",
            "mask_image": "--mask-image",
            "strength": "--strength",
            "lora_scale": "--lora-scale",
            "width": "--width",
            "height": "--height",
            "steps": "--steps",
            "guidance_scale": "--guidance-scale",
            "seed": "--seed",
            "output_dir": "--output-dir",
            "filename": "--filename",
        }
        for key, flag in mapping.items():
            if key in arguments and arguments[key] is not None:
                args.extend([flag, str(arguments[key])])
        loras = arguments.get("lora") or []
        for lora in loras:
            args.extend(["--lora", str(lora)])
        if arguments.get("allow_cpu"):
            args.append("--allow-cpu")
        if arguments.get("cpu_offload"):
            args.append("--cpu-offload")
        if arguments.get("vae_tiling"):
            args.append("--vae-tiling")
        if arguments.get("disable_safety_checker"):
            args.append("--disable-safety-checker")
        if arguments.get("allow_download"):
            args.append("--allow-download")
        code, stdout, stderr = run_script("generate_image.py", args)
        return script_json_result("generate_image.py", code, stdout, stderr)

    try:
        if name in {
            "local_gpu_discover_models",
            "local_gpu_set_model_trust",
            "local_gpu_recommend_models",
        }:
            services = get_runtime_services()
            if name == "local_gpu_discover_models":
                return tool_success(_successful_engine_data(_discovery_call(services, arguments)))
            if name == "local_gpu_set_model_trust":
                return tool_success(_successful_engine_data(_trust_call(services, arguments)))
            return tool_success(_successful_engine_data(services.router.recommend(arguments)))
        engine = get_asset_engine()
        if name == "local_gpu_list_profiles":
            data = _successful_engine_data(engine.list_profiles(arguments.get("authorization_scope", "private")))
            return tool_success(data)
        if name == "local_gpu_start_run":
            data = _successful_engine_data(engine.start_run(arguments))
            return tool_success(data)
        if name == "local_gpu_get_run":
            data = _successful_engine_data(engine.get_run(arguments))
            return tool_success(data)
        if name == "local_gpu_branch_run":
            data = _successful_engine_data(engine.branch_run(arguments))
            return tool_success(data)
        if name == "local_gpu_prepare_mask":
            data, preview = engine.prepare_mask(arguments)
            return tool_success(_successful_engine_data(data), _preview_block(preview))
        if name == "local_gpu_confirm_mask":
            data = _successful_engine_data(engine.confirm_mask(arguments))
            return tool_success(data)
        if name == "local_gpu_generate_round":
            data, preview = engine.generate_round(arguments)
            return tool_success(_successful_engine_data(data), _preview_block(preview))
        if name == "local_gpu_record_review":
            review = {
                field: arguments[field]
                for field in (
                    "scores", "hard_failures", "critique", "constraint_results",
                    "preservation_results", "next_action",
                )
                if field in arguments
            }
            data = _successful_engine_data(engine.record_review({
                "run_id": arguments["run_id"],
                "round_number": arguments["round_number"],
                "review": review,
            }))
            return tool_success(data)
        if name == "local_gpu_finalize_run":
            data = _successful_engine_data(engine.finalize_run(arguments))
            return tool_success(data)
        if name == "local_gpu_cleanup_run":
            data = _successful_engine_data(engine.cleanup_run(arguments))
            return tool_success(data)
    except AssetEngineError as error:
        return _asset_error(error)

    raise AssertionError(f"Unhandled tool schema: {name}")


def handle_request(request: dict[str, Any]) -> None:
    request_id = request.get("id")
    method = request.get("method")

    if request_id is None:
        return

    if request.get("jsonrpc") != "2.0":
        send(jsonrpc_error(request_id, -32600, "jsonrpc must be 2.0", "invalid_request"))
        return

    if method == "initialize":
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "local-gpu-imagegen", "version": SERVER_VERSION},
                },
            }
        )
        return

    if method == "tools/list":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_schema()}})
        return

    if method == "ping":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        return

    if method == "tools/call":
        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            send(jsonrpc_error(request_id, -32602, "tools/call params must be a JSON object.", "invalid_params"))
            return
        send({"jsonrpc": "2.0", "id": request_id, "result": handle_tool_call(params)})
        return

    send(jsonrpc_error(request_id, -32601, f"Method not found: {method}", "method_not_found"))


def process_line(line: str) -> None:
    try:
        request = json.loads(line.lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        send(
            jsonrpc_error(
                None,
                -32700,
                "Parse error.",
                "parse_error",
                {"line": exc.lineno, "column": exc.colno},
            )
        )
        return

    if not isinstance(request, dict):
        send(jsonrpc_error(None, -32600, "Request must be a JSON object.", "invalid_request"))
        return

    request_id = request.get("id")
    try:
        handle_request(request)
    except Exception as exc:
        send(
            jsonrpc_error(
                request_id,
                -32603,
                "Internal server error.",
                "internal_error",
                {"exceptionType": type(exc).__name__},
            )
        )


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        process_line(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
