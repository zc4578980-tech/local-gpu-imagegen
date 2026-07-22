from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Sequence


def render_client_config(client: str) -> str:
    if client == "codex":
        return "\n".join(
            (
                "[mcp_servers.local-gpu-imagegen]",
                'command = "local-gpu-imagegen"',
                'args = ["serve"]',
            )
        )
    if client == "claude-desktop":
        return json.dumps(
            {
                "mcpServers": {
                    "local-gpu-imagegen": {
                        "command": "local-gpu-imagegen",
                        "args": ["serve"],
                    }
                }
            },
            indent=2,
        )
    raise ValueError(f"Unsupported client: {client}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-gpu-imagegen",
        description="Run and verify the local GPU Imagegen MCP control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="Serve MCP over standard input/output.")
    subparsers.add_parser("doctor", help="Report local backend readiness as JSON.")
    verify = subparsers.add_parser("verify", help="Verify the exact MCP stdio contract.")
    verify.add_argument("--python", default=sys.executable, help="Python used to launch the MCP server.")
    verify.add_argument("--check-readiness", action="store_true", help="Also call the readiness tool.")
    config = subparsers.add_parser("config", help="Print an installed-command client configuration.")
    config.add_argument("client", choices=("codex", "claude-desktop"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        import mcp_server

        return mcp_server.main()
    if args.command == "doctor":
        import check_gpu

        return check_gpu.main()
    if args.command == "config":
        print(render_client_config(args.client))
        return 0
    if args.command == "verify":
        import verify_mcp

        try:
            report = verify_mcp.verify(args.python, args.check_readiness)
        except (json.JSONDecodeError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
