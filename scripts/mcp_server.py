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


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PYTHON = sys.executable
DEFAULT_COMMAND_TIMEOUT_SECONDS = int(os.environ.get("LOCAL_GPU_IMAGEGEN_COMMAND_TIMEOUT_SECONDS", "900"))
MAX_PREVIEW_BASE64_CHARS = 4 * ((1024 * 1024 + 2) // 3)
_asset_engine: Any | None = None


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
    return {**value, "available_backends": available_backends}


def get_asset_engine() -> Any:
    global _asset_engine
    if _asset_engine is None:
        from local_gpu_imagegen.engine import AssetRunEngine
        from local_gpu_imagegen.profile_registry import ProfileRegistry
        from local_gpu_imagegen.run_store import RunStore

        registry = ProfileRegistry(ROOT / "profiles")
        store = RunStore(Path(os.environ.get("LOCAL_GPU_IMAGEGEN_OUTPUT_DIR", ROOT / "outputs")))
        _asset_engine = AssetRunEngine(
            registry,
            store,
            lambda args: run_script("generate_image.py", args),
            get_capabilities,
        )
    return _asset_engine


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
    return _object_schema({**common, **properties}, ["ok", *required, "warnings"])


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
    run_manifest_properties = {
        "run_id": {"type": "string"},
        "schema_version": {"type": "integer"},
        "manifest_revision": {"type": "integer"},
        "state": {"type": "string"},
        "last_stable_state": {"type": "string"},
        "active_attempt": json_value,
        "parent": json_value,
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
            "name": "local_gpu_list_profiles",
            "description": "List registered visual-asset profiles and current local backend capabilities.",
            "inputSchema": _object_schema({}, []),
            "outputSchema": _output_schema({
                "profiles": json_object,
                "styles": json_object,
                "capabilities": json_object,
            }, ["profiles", "styles", "capabilities"]),
        },
        {
            "name": "local_gpu_start_run",
            "description": "Create a confirmed visual-asset run.",
            "inputSchema": _object_schema({
                "intent": {"type": "string", "minLength": 1},
                "profile": {"type": "string", "enum": _registered_profile_ids()},
                "style": {"type": ["string", "null"], "enum": [None, *_registered_style_ids()]},
                "constraints": json_object,
                "backend": {"type": "string", "enum": ["auto", "webui", "diffusers"]},
                "max_rounds": {"type": "integer", "minimum": 1, "maximum": 3},
                "upscale_policy": {"type": "string", "enum": ["auto", "off"]},
            }, ["intent", "profile", "style", "constraints", "backend", "max_rounds", "upscale_policy"]),
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
            "name": "local_gpu_generate_round",
            "description": "Generate one confirmed txt2img round and return an optional bounded JPEG preview.",
            "inputSchema": _object_schema({
                "run_id": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
                "action": {"type": "string", "enum": ["initial", "refine", "explore"]},
                "edit_mode": {"type": "string", "const": "txt2img"},
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
            item_type = field_schema["items"].get("type")
            if item_type and not all(schema_type_matches(item, item_type) for item in value):
                return tool_error(
                    "invalid_lora" if field == "lora" else "invalid_argument_type",
                    "validation",
                    f"{field} must be an array of {item_type}s.",
                    {"field": field, "itemType": item_type},
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
        engine = get_asset_engine()
        if name == "local_gpu_list_profiles":
            data = _successful_engine_data(engine.list_profiles())
            return tool_success(data)
        if name == "local_gpu_start_run":
            data = _successful_engine_data(engine.start_run(arguments))
            return tool_success(data)
        if name == "local_gpu_get_run":
            data = _successful_engine_data(engine.get_run(arguments))
            return tool_success(data)
        if name == "local_gpu_generate_round":
            data, preview = engine.generate_round(arguments)
            return tool_success(_successful_engine_data(data), _preview_block(preview))
        if name == "local_gpu_record_review":
            review = {
                field: arguments[field]
                for field in ("scores", "hard_failures", "critique", "constraint_results", "next_action")
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
                    "serverInfo": {"name": "local-gpu-imagegen", "version": "0.2.0"},
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
