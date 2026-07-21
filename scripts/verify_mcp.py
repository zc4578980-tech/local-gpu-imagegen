#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "mcp_server.py"
REQUIRED_COMPATIBILITY_TOOLS = {"local_gpu_imagegen_check", "local_gpu_generate_image"}


def build_requests(include_readiness: bool = False) -> str:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}},
    ]
    if include_readiness:
        requests.append(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "local_gpu_imagegen_check", "arguments": {}},
            }
        )
    return "\n".join(json.dumps(request) for request in requests) + "\n"


def verify(
    python_executable: str = sys.executable,
    check_readiness: bool = False,
    expected_tools: set[str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        [python_executable, str(SERVER)],
        input=build_requests(check_readiness),
        capture_output=True,
        text=True,
        errors="replace",
        cwd=ROOT,
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"MCP server exited with code {completed.returncode}: {completed.stderr.strip()}")

    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    by_id = {response.get("id"): response for response in responses}
    expected_ids = {1, 2, 3, 4} if check_readiness else {1, 2, 3}
    if set(by_id) != expected_ids:
        raise RuntimeError(f"Expected response IDs {sorted(expected_ids)}; received {sorted(by_id)}.")
    for request_id, response in by_id.items():
        if "error" in response:
            raise RuntimeError(f"Request {request_id} failed: {response['error']}")

    initialize = by_id[1]["result"]
    tools = {tool["name"] for tool in by_id[2]["result"]["tools"]}
    missing_compatibility_tools = REQUIRED_COMPATIBILITY_TOOLS - tools
    if missing_compatibility_tools:
        raise RuntimeError(f"Missing compatibility tools: {sorted(missing_compatibility_tools)}")
    if expected_tools is not None and tools != expected_tools:
        raise RuntimeError(f"Unexpected tools: {sorted(tools)}")
    if by_id[3]["result"] != {}:
        raise RuntimeError("Ping did not return an empty result object.")

    report = {
        "ok": True,
        "transport": "stdio",
        "python": python_executable,
        "server": initialize["serverInfo"],
        "protocolVersion": initialize["protocolVersion"],
        "tools": sorted(tools),
    }
    if check_readiness:
        tool_result = by_id[4]["result"]
        if tool_result.get("isError"):
            raise RuntimeError(f"Readiness tool failed: {tool_result.get('structuredContent')}")
        readiness = tool_result.get("structuredContent")
        if not isinstance(readiness, dict) or not isinstance(readiness.get("ready"), bool):
            raise RuntimeError("Readiness tool did not return structuredContent.ready as a boolean.")
        report["readiness"] = readiness
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the local GPU Imagegen MCP stdio contract.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to launch the MCP server.")
    parser.add_argument(
        "--check-readiness",
        action="store_true",
        help="Also call local_gpu_imagegen_check and validate its structured result.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = verify(args.python, args.check_readiness)
    except (json.JSONDecodeError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
