from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence


SERVER_NAME = "local-gpu-imagegen"
SERVER_COMMAND = ("local-gpu-imagegen", "serve")
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

    version_result = _run(runner, [executable, "--version"])
    if version_result.returncode != 0:
        raise RuntimeError(f"client_version_failed:{client}")
    version = (version_result.stdout or "").strip()
    if not version:
        raise RuntimeError(f"client_version_failed:{client}")

    existing_result = _run(runner, _command(executable, definition["get"]))
    return {
        "client": client,
        "detected": True,
        "version": version[:MAX_ERROR_LENGTH],
        "server": {"name": SERVER_NAME, "command": list(SERVER_COMMAND)},
        "existing": existing_result.returncode == 0,
        "add_command": _command(executable, definition["add"]),
        "remove_command": _command(executable, definition["remove"]),
        "applied": False,
        "status": "already_configured" if existing_result.returncode == 0 else "planned",
    }


def apply_setup_plan(
    plan: dict[str, object],
    *,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    if plan.get("existing") is True:
        return {**plan, "status": "already_configured"}

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
