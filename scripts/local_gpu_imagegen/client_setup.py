from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence

from local_gpu_imagegen import __version__
from local_gpu_imagegen.backend_lifecycle import (
    DEFAULT_COMFYUI_URL,
    DEFAULT_START_TIMEOUT_SECONDS,
    build_comfyui_start_config,
)


SERVER_NAME = "local-gpu-imagegen"
SERVER_COMMAND = (
    "uvx",
    "--from",
    f"local-gpu-imagegen=={__version__}",
    "local-gpu-imagegen",
    "serve",
)
SUBPROCESS_TIMEOUT_SECONDS = 15
MAX_ERROR_LENGTH = 500

CLIENTS: dict[str, dict[str, object]] = {
    "codex": {
        "binary": "codex",
        "get": ("mcp", "get", SERVER_NAME, "--json"),
        "add": ("mcp", "add", SERVER_NAME, "--", *SERVER_COMMAND),
        "remove": ("mcp", "remove", SERVER_NAME),
    },
    "claude-code": {
        "binary": "claude",
        "get": ("mcp", "get", SERVER_NAME),
        "add": (
            "mcp",
            "add",
            "--scope",
            "user",
            SERVER_NAME,
            "--",
            *SERVER_COMMAND,
        ),
        "remove": ("mcp", "remove", "--scope", "user", SERVER_NAME),
    },
}

ExecutableLookup = Callable[[str], str | None]
Runner = Callable[..., subprocess.CompletedProcess[str]]


def managed_comfyui_server_command(
    root: str | os.PathLike[str],
    *,
    base_url: str = DEFAULT_COMFYUI_URL,
    timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    config = build_comfyui_start_config(
        root,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    timeout = str(int(config.timeout_seconds)) if config.timeout_seconds.is_integer() else str(
        config.timeout_seconds
    )
    return (
        *SERVER_COMMAND,
        "--auto-start-comfyui",
        "--comfyui-root",
        str(config.root),
        "--comfyui-url",
        config.base_url,
        "--comfyui-start-timeout-seconds",
        timeout,
    )


def _run(runner: Runner, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return runner(
        list(argv),
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _arguments(value: object) -> list[str]:
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise RuntimeError("invalid_client_setup_definition")
    return list(value)


def _command(executable: str, value: object) -> list[str]:
    return [executable, *_arguments(value)]


def _same_executable(observed: str, expected: str) -> bool:
    return os.path.normcase(os.path.normpath(observed)) == os.path.normcase(
        os.path.normpath(expected)
    )


def _existing_server_command(client: str, stdout: str) -> list[str] | None:
    if client == "codex":
        try:
            document = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        transport = document.get("transport")
        if not isinstance(transport, dict):
            return None
        command = transport.get("command")
        args = transport.get("args")
        if not isinstance(command, str) or not isinstance(args, list):
            return None
        if not all(isinstance(item, str) for item in args):
            return None
        return [command, *args]
    if client == "claude-code":
        command_match = re.search(r"(?m)^\s*Command:\s*(.+?)\s*$", stdout)
        args_match = re.search(r"(?m)^\s*Args:\s*(.*?)\s*$", stdout)
        if command_match is None or args_match is None:
            return None
        try:
            args = shlex.split(args_match.group(1), posix=False)
        except ValueError:
            return None
        args = [
            item[1:-1]
            if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"}
            else item
            for item in args
        ]
        return [command_match.group(1), *args]
    return None


def _existing_matches(client: str, stdout: str, expected: Sequence[str]) -> bool:
    observed = _existing_server_command(client, stdout)
    return bool(
        observed
        and len(observed) == len(expected)
        and _same_executable(observed[0], expected[0])
        and observed[1:] == list(expected[1:])
    )


def setup_contract(client: str) -> dict[str, object]:
    definition = CLIENTS.get(client)
    if definition is None:
        raise ValueError(f"unsupported_client:{client}")
    binary = definition["binary"]
    if not isinstance(binary, str):
        raise RuntimeError("invalid_client_setup_definition")
    add_args = _arguments(definition["add"])
    remove_args = _arguments(definition["remove"])
    return {
        "client": client,
        "binary": binary,
        "server": {"name": SERVER_NAME, "command": list(SERVER_COMMAND)},
        "add_args": add_args,
        "remove_args": remove_args,
    }


def build_setup_plan(
    client: str,
    *,
    server_command: Sequence[str] = SERVER_COMMAND,
    executable_lookup: ExecutableLookup = shutil.which,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    definition = CLIENTS.get(client)
    if definition is None:
        raise ValueError(f"unsupported_client:{client}")

    binary = definition["binary"]
    if not isinstance(binary, str):
        raise RuntimeError("invalid_client_setup_definition")
    executable = executable_lookup(binary)
    if executable is None:
        raise RuntimeError(f"client_not_found:{binary}")
    if not server_command or not all(isinstance(item, str) and item for item in server_command):
        raise RuntimeError("invalid_server_command")
    server_executable = executable_lookup(server_command[0])
    if server_executable is None:
        raise RuntimeError(f"server_launcher_not_found:{server_command[0]}")
    resolved_server_command = [server_executable, *server_command[1:]]

    version_result = _run(runner, [executable, "--version"])
    if version_result.returncode != 0:
        raise RuntimeError(f"client_version_failed:{client}")
    version = (version_result.stdout or "").strip()
    if not version:
        raise RuntimeError(f"client_version_failed:{client}")

    existing_result = _run(runner, _command(executable, definition["get"]))
    add_args = _arguments(definition["add"])
    add_args[-len(SERVER_COMMAND) :] = resolved_server_command
    existing = existing_result.returncode == 0
    existing_matches = existing and _existing_matches(
        client,
        existing_result.stdout or "",
        resolved_server_command,
    )
    return {
        "client": client,
        "detected": True,
        "version": version[:MAX_ERROR_LENGTH],
        "server": {"name": SERVER_NAME, "command": resolved_server_command},
        "existing": existing,
        "existing_matches": existing_matches,
        "add_command": [executable, *add_args],
        "remove_command": _command(executable, definition["remove"]),
        "applied": False,
        "status": (
            "already_configured"
            if existing_matches
            else "configuration_drift" if existing else "planned"
        ),
    }


def apply_setup_plan(
    plan: dict[str, object],
    *,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    if plan.get("existing") is True:
        if plan.get("existing_matches") is True:
            return {**plan, "status": "already_configured"}
        client = plan.get("client", "unknown")
        raise RuntimeError(f"client_setup_drift:{client}:remove_then_reapply")

    add_command = plan.get("add_command")
    if not isinstance(add_command, list) or not all(
        isinstance(item, str) for item in add_command
    ):
        raise RuntimeError("invalid_client_setup_plan")
    completed = _run(runner, add_command)
    if completed.returncode != 0:
        client = plan.get("client", "unknown")
        stderr = (completed.stderr or "").strip()[:MAX_ERROR_LENGTH]
        raise RuntimeError(f"client_setup_failed:{client}:{stderr}")
    return {**plan, "applied": True, "status": "configured"}
