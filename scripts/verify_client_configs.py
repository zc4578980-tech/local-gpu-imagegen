#!/usr/bin/env python
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from typing import Any

from local_gpu_imagegen.cli import render_client_config
from verify_mcp import verify


EXPECTED_COMMAND = {"command": "local-gpu-imagegen", "args": ["serve"]}


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


def verify_client_configs() -> dict[str, Any]:
    clients: dict[str, Any] = {}
    for client in ("codex", "claude-desktop"):
        config = _parse_client_config(client)
        stdio = verify()
        clients[client] = {
            **config,
            "config_valid": True,
            "server": stdio["server"],
            "protocol_version": stdio["protocolVersion"],
            "tools": stdio["tools"],
        }
    if clients["codex"]["server"] != clients["claude-desktop"]["server"]:
        raise RuntimeError("Named configurations did not resolve to the same MCP server identity.")
    if clients["codex"]["tools"] != clients["claude-desktop"]["tools"]:
        raise RuntimeError("Named configurations did not expose the same MCP tool contract.")
    return {
        "ok": True,
        "verification_scope": "configuration_contract_and_stdio_launch",
        "hosted_client_session": False,
        "clients": clients,
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
