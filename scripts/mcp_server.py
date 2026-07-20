#!/usr/bin/env python
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PYTHON = sys.executable
DEFAULT_COMMAND_TIMEOUT_SECONDS = int(os.environ.get("LOCAL_GPU_IMAGEGEN_COMMAND_TIMEOUT_SECONDS", "900"))


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


def tool_success(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": text_content(json.dumps(data, indent=2)),
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


def tool_schema() -> list[dict[str, Any]]:
    return [
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


def schema_type_matches(value: object, schema_type: str) -> bool:
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
            return tool_error(
                "invalid_prompt" if field == "prompt" else "missing_argument",
                "validation",
                f"local_gpu_generate_image requires a non-empty {field}.",
                {"field": field},
            )

    for field, value in arguments.items():
        field_schema = properties[field]
        expected_type = field_schema.get("type")
        if expected_type and not schema_type_matches(value, expected_type):
            code = "invalid_lora" if field == "lora" else "invalid_argument_type"
            message = "lora must be an array of strings." if field == "lora" else f"{field} must be a JSON {expected_type}."
            return tool_error(code, "validation", message, {"field": field, "expectedType": expected_type})
        if "enum" in field_schema and value not in field_schema["enum"]:
            return tool_error(
                "invalid_argument_value",
                "validation",
                f"{field} must be one of: {', '.join(field_schema['enum'])}.",
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
    return None


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
