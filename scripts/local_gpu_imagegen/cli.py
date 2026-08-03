from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Sequence

from local_gpu_imagegen.client_setup import SERVER_COMMAND


def render_client_config(client: str) -> str:
    if client == "codex":
        return "\n".join(
            (
                "[mcp_servers.local-gpu-imagegen]",
                f'command = "{SERVER_COMMAND[0]}"',
                f"args = {json.dumps(list(SERVER_COMMAND[1:]))}",
            )
        )
    if client == "claude-desktop":
        return json.dumps(
            {
                "mcpServers": {
                    "local-gpu-imagegen": {
                        "command": SERVER_COMMAND[0],
                        "args": list(SERVER_COMMAND[1:]),
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
    serve = subparsers.add_parser("serve", help="Serve MCP over standard input/output.")
    serve.add_argument(
        "--auto-start-comfyui",
        action="store_true",
        help="Start and own one explicitly configured Windows portable ComfyUI.",
    )
    serve.add_argument("--comfyui-root", help="Existing ComfyUI_windows_portable root.")
    serve.add_argument(
        "--comfyui-url",
        default="http://127.0.0.1:8188",
        help="Loopback-only managed endpoint.",
    )
    serve.add_argument(
        "--comfyui-start-timeout-seconds",
        type=float,
        default=120.0,
        help="Maximum first readiness wait, from 1 through 300 seconds.",
    )
    subparsers.add_parser("doctor", help="Report local backend readiness as JSON.")
    verify = subparsers.add_parser("verify", help="Verify the exact MCP stdio contract.")
    verify.add_argument("--python", default=sys.executable, help="Python used to launch the MCP server.")
    verify.add_argument("--check-readiness", action="store_true", help="Also call the readiness tool.")
    config = subparsers.add_parser("config", help="Print an installed-command client configuration.")
    config.add_argument("client", choices=("codex", "claude-desktop"))
    setup = subparsers.add_parser("setup", help="Plan or apply official MCP client setup.")
    setup.add_argument("client", choices=("codex", "claude-code"))
    setup.add_argument(
        "--apply",
        action="store_true",
        help="Apply the displayed plan through the client's official mcp add command.",
    )
    setup.add_argument(
        "--auto-start-comfyui",
        action="store_true",
        help="Register an MCP command that owns an explicit portable ComfyUI child.",
    )
    setup.add_argument("--comfyui-root", help="Existing ComfyUI_windows_portable root.")
    setup.add_argument("--comfyui-url", default="http://127.0.0.1:8188")
    setup.add_argument("--comfyui-start-timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        import mcp_server

        if not args.auto_start_comfyui:
            if (
                args.comfyui_root is not None
                or args.comfyui_url != "http://127.0.0.1:8188"
                or args.comfyui_start_timeout_seconds != 120.0
            ):
                print(
                    json.dumps({"ok": False, "error": "comfyui_options_require_autostart"}),
                    file=sys.stderr,
                )
                return 1
            return mcp_server.main()
        try:
            from local_gpu_imagegen.backend_lifecycle import (
                ComfyUIProcessSupervisor,
                build_comfyui_start_config,
            )

            if args.comfyui_root is None:
                raise ValueError("comfyui_autostart_requires_root")
            config = build_comfyui_start_config(
                args.comfyui_root,
                base_url=args.comfyui_url,
                timeout_seconds=args.comfyui_start_timeout_seconds,
            )
            supervisor = ComfyUIProcessSupervisor(config)
            supervisor.start()
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 1
        try:
            return mcp_server.main()
        finally:
            cleanup = supervisor.close()
            if cleanup.get("cleanup_status") in {
                "retained_nonempty_queue",
                "retained_unknown_queue",
                "terminate_timeout",
            }:
                print(json.dumps({"backend_cleanup": cleanup}), file=sys.stderr)
    if args.command == "doctor":
        import check_gpu

        return check_gpu.main()
    if args.command == "config":
        print(render_client_config(args.client))
        return 0
    if args.command == "setup":
        import check_gpu

        from local_gpu_imagegen.client_setup import (
            apply_setup_plan,
            build_setup_plan,
            managed_comfyui_server_command,
        )

        try:
            if args.auto_start_comfyui:
                if args.comfyui_root is None:
                    raise ValueError("comfyui_autostart_requires_root")
                command = managed_comfyui_server_command(
                    args.comfyui_root,
                    base_url=args.comfyui_url,
                    timeout_seconds=args.comfyui_start_timeout_seconds,
                )
                plan = build_setup_plan(args.client, server_command=command)
            else:
                if (
                    args.comfyui_root is not None
                    or args.comfyui_url != "http://127.0.0.1:8188"
                    or args.comfyui_start_timeout_seconds != 120.0
                ):
                    raise ValueError("comfyui_options_require_autostart")
                plan = build_setup_plan(args.client)
            result = apply_setup_plan(plan) if args.apply else plan
            report = {
                "ok": True,
                **result,
                "backend_readiness": check_gpu.collect_report(),
            }
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2))
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
