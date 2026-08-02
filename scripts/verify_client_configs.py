#!/usr/bin/env python
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from typing import Any

from local_gpu_imagegen.cli import render_client_config
from local_gpu_imagegen.client_setup import SERVER_COMMAND, setup_contract
from verify_mcp import verify


EXPECTED_COMMAND = {
    "command": SERVER_COMMAND[0],
    "args": list(SERVER_COMMAND[1:]),
}
EXPECTED_SETUP_SERVER = {
    "name": "local-gpu-imagegen",
    "command": list(SERVER_COMMAND),
}


def _parse_client_config(client: str) -> dict[str, Any]:
    rendered = render_client_config(client)
    if client == "codex":
        command = tomllib.loads(rendered)["mcp_servers"]["local-gpu-imagegen"]
        config_format = "toml"
    elif client == "claude-desktop":
        command = json.loads(rendered)["mcpServers"]["local-gpu-imagegen"]
        config_format = "json"
    else:
        raise ValueError(f"Unsupported client: {client}")
    if command != EXPECTED_COMMAND:
        raise RuntimeError(f"{client} configuration does not resolve to the installed stdio command.")
    return {"format": config_format, "command": command}


def _parse_setup_contract(client: str) -> dict[str, Any]:
    contract = setup_contract(client)
    if contract["server"] != EXPECTED_SETUP_SERVER:
        raise RuntimeError(f"{client} setup does not resolve to the installed stdio command.")
    launcher = shutil.which(SERVER_COMMAND[0])
    if launcher is None:
        raise RuntimeError(f"{client} setup launcher is not executable: {SERVER_COMMAND[0]}")
    return {
        "configuration_kind": "official_cli_setup_contract",
        "format": "official_cli",
        "launcher": SERVER_COMMAND[0],
        "launcher_resolved": True,
        "setup": contract,
    }


def verify_client_configs() -> dict[str, Any]:
    clients: dict[str, Any] = {}
    for client in ("codex", "claude-code"):
        config = _parse_setup_contract(client)
        stdio = verify()
        clients[client] = {
            **config,
            "config_valid": True,
            "server": stdio["server"],
            "protocol_version": stdio["protocolVersion"],
            "tools": stdio["tools"],
        }
    if clients["codex"]["server"] != clients["claude-code"]["server"]:
        raise RuntimeError("Named configurations did not resolve to the same MCP server identity.")
    if clients["codex"]["tools"] != clients["claude-code"]["tools"]:
        raise RuntimeError("Named configurations did not expose the same MCP tool contract.")
    legacy = _parse_client_config("claude-desktop")
    return {
        "ok": True,
        "verification_scope": "configuration_contract_and_stdio_launch",
        "hosted_client_session": False,
        "clients": clients,
        "legacy_templates": {
            "claude-desktop": {
                **legacy,
                "configuration_kind": "render_only_template",
                "config_valid": True,
            }
        },
    }


def main() -> int:
    try:
        report = verify_client_configs()
    except (json.JSONDecodeError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired, tomllib.TOMLDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
