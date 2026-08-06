from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from local_gpu_imagegen.bootstrap_catalog import (
    BootstrapFacts,
    BootstrapManifest,
    BootstrapPlan,
    build_bootstrap_plan,
    load_bootstrap_manifest,
)
from local_gpu_imagegen.bootstrap_service import apply_bootstrap_plan
from local_gpu_imagegen.backend_lifecycle import build_comfyui_start_config
from local_gpu_imagegen.client_setup import SERVER_COMMAND
from local_gpu_imagegen.errors import ArtifactError, StateError, ValidationError
from local_gpu_imagegen.paths import default_bootstrap_paths, resolve_resource_root


_MAX_BOOTSTRAP_STATE_BYTES = 512 * 1024
_MAX_BOOTSTRAP_RECORDS = 128
_BOOTSTRAP_PLAN_ID = re.compile(r"[0-9a-f]{24}\Z")
_PLAN_RECORD_FIELDS = frozenset({"schema_version", "plan_id", "scope_sha256", "confirmation", "scope"})
_TRANSACTION_RECORD_FIELDS = frozenset({
    "schema_version",
    "plan_id",
    "scope_sha256",
    "confirmation_sha256",
    "status",
    "downloaded_artifacts",
    "failure_code",
    "retained_state",
    "recoverable_next_actions",
})


def _gpu_generation(name: object) -> str:
    normalized = str(name).lower()
    for generation in ("50", "40", "30", "20"):
        if f"rtx {generation}" in normalized or f"rtx{generation}" in normalized:
            return f"rtx-{generation}-series"
    return "unknown"


def _disk_usage_parent(path: Path) -> Path:
    candidate = Path(path).expanduser()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def _read_bootstrap_record(path: Path) -> dict[str, object] | None:
    descriptor: int | None = None
    try:
        metadata = path.lstat()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)
            or metadata.st_nlink != 1
        ):
            return None
        if metadata.st_size < 1 or metadata.st_size > _MAX_BOOTSTRAP_STATE_BYTES:
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(str(path), flags)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            opened = os.fstat(stream.fileno())
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_ISLNK(opened.st_mode)
                or bool(getattr(opened, "st_file_attributes", 0) & reparse_flag)
                or opened.st_nlink != 1
                or opened.st_size < 1
                or opened.st_size > _MAX_BOOTSTRAP_STATE_BYTES
                or not os.path.samestat(metadata, opened)
                or not os.path.samestat(current, opened)
            ):
                return None
            raw = stream.read(_MAX_BOOTSTRAP_STATE_BYTES + 1)
        if len(raw) > _MAX_BOOTSTRAP_STATE_BYTES:
            return None
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    return document if isinstance(document, dict) else None


def _regular_file_size(path: Path, expected_size: int) -> bool:
    descriptor: int | None = None
    try:
        metadata = path.lstat()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)
            or metadata.st_nlink != 1
            or metadata.st_size != expected_size
        ):
            return False
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        current = path.lstat()
        return (
            stat.S_ISREG(opened.st_mode)
            and not stat.S_ISLNK(opened.st_mode)
            and not bool(getattr(opened, "st_file_attributes", 0) & reparse_flag)
            and opened.st_nlink == 1
            and opened.st_size == expected_size
            and os.path.samestat(metadata, opened)
            and os.path.samestat(current, opened)
        )
    except OSError:
        return False
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _matching_transaction_evidence(
    paths,
    manifest: BootstrapManifest,
) -> tuple[str, dict[str, object]] | None:
    try:
        root_metadata = paths.plans.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
            return None
        entries: list[Path] = []
        with os.scandir(paths.plans) as iterator:
            for entry in iterator:
                if not entry.name.endswith(".transaction.json"):
                    continue
                entries.append(Path(entry.path))
                if len(entries) > _MAX_BOOTSTRAP_RECORDS:
                    return None
        entries.sort()
    except OSError:
        return None
    resolved_install_root = str(paths.install.expanduser().resolve())
    matching_transactions: dict[str, dict[str, object]] = {}
    for transaction_path in entries:
        transaction = _read_bootstrap_record(transaction_path)
        if transaction is None or set(transaction) != _TRANSACTION_RECORD_FIELDS:
            continue
        plan_id = transaction.get("plan_id")
        if not isinstance(plan_id, str) or _BOOTSTRAP_PLAN_ID.fullmatch(plan_id) is None:
            continue
        plan = _read_bootstrap_record(paths.plans / f"{plan_id}.json")
        if plan is None or set(plan) != _PLAN_RECORD_FIELDS:
            continue
        scope = plan.get("scope")
        if isinstance(scope, dict):
            canonical_scope = json.dumps(
                scope,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
            scope_sha256 = hashlib.sha256(canonical_scope).hexdigest()
        else:
            scope_sha256 = None
        if (
            plan.get("schema_version") != 1
            or plan.get("plan_id") != plan_id
            or plan.get("scope_sha256") != scope_sha256
            or scope_sha256 is None
            or plan_id != scope_sha256[:24]
            or transaction.get("scope_sha256") != scope_sha256
            or not isinstance(plan.get("confirmation"), str)
            or transaction.get("confirmation_sha256") != hashlib.sha256(
                str(plan.get("confirmation")).encode("utf-8")
            ).hexdigest()
            or not isinstance(scope, dict)
            or scope.get("manifest_sha256") != manifest.manifest_sha256
            or scope.get("install_root") != resolved_install_root
        ):
            continue
        status = transaction.get("status")
        if status in {"completed", "failed", "in_progress"}:
            matching_transactions[status] = transaction
    for status in ("completed", "in_progress", "failed"):
        if status in matching_transactions:
            return status, matching_transactions[status]
    return None


def _matching_transaction_status(paths, manifest: BootstrapManifest) -> str | None:
    evidence = _matching_transaction_evidence(paths, manifest)
    return evidence[0] if evidence is not None else None


def _completed_model_evidence(
    transaction: dict[str, object],
    manifest: BootstrapManifest,
    model_path: Path,
) -> bool:
    retained_state = transaction.get("retained_state")
    downloaded_artifacts = transaction.get("downloaded_artifacts")
    if (
        not isinstance(retained_state, dict)
        or set(retained_state) != {"portable", "model", "verified_cache_artifacts"}
        or retained_state.get("portable") not in {"installed", "verified_pre_existing"}
        or retained_state.get("model") not in {"installed", "verified_pre_existing"}
        or not isinstance(downloaded_artifacts, list)
        or any(not isinstance(item, str) or not item for item in downloaded_artifacts)
        or len(downloaded_artifacts) != len(set(downloaded_artifacts))
        or retained_state.get("verified_cache_artifacts") != downloaded_artifacts
    ):
        return False
    for component, artifact in (
        ("portable", manifest.comfyui),
        ("model", manifest.model),
    ):
        downloaded = artifact.artifact_id in downloaded_artifacts
        if retained_state.get(component) == "installed" and not downloaded:
            return False
        if retained_state.get(component) == "verified_pre_existing" and downloaded:
            return False
    return _regular_file_size(model_path, manifest.model.byte_size)


def _bootstrap_local_state(paths, manifest: BootstrapManifest) -> dict[str, object]:
    portable_root = paths.install / manifest.comfyui.install_relative_path
    model_path = paths.install / manifest.model.install_relative_path
    evidence = _matching_transaction_evidence(paths, manifest)
    transaction_status = evidence[0] if evidence is not None else None
    transaction = evidence[1] if evidence is not None else None
    portable_valid = False
    if transaction_status == "completed":
        try:
            build_comfyui_start_config(portable_root)
            portable_valid = True
        except (OSError, RuntimeError, ValueError):
            portable_valid = False
        if (
            portable_valid
            and transaction is not None
            and _completed_model_evidence(transaction, manifest, model_path)
        ):
            return {
                "status": "installed",
                "reason_codes": [],
                "portable_status": "valid",
                "model_status": "valid",
            }
        return {
            "status": "recoverable",
            "reason_codes": ["completed_transaction_evidence_drift"],
            "portable_status": "conflict",
            "model_status": "conflict",
        }
    if transaction_status in {"failed", "in_progress"}:
        return {
            "status": "recoverable",
            "reason_codes": ["bootstrap_transaction_recovery_required"],
            "portable_status": "conflict",
            "model_status": "conflict",
        }
    if portable_root.exists() or model_path.exists():
        return {
            "status": "unknown",
            "reason_codes": ["unverified_existing_installation"],
            "portable_status": "conflict" if portable_root.exists() else "missing",
            "model_status": "conflict" if model_path.exists() else "missing",
        }
    return {
        "status": "not_installed",
        "reason_codes": [],
        "portable_status": "missing",
        "model_status": "missing",
    }


def _collect_bootstrap_facts(paths, manifest: BootstrapManifest) -> BootstrapFacts:
    """Build conservative planner facts from the existing readiness report."""
    import check_gpu

    report = check_gpu.collect_report()
    cuda = report.get("cuda") if isinstance(report.get("cuda"), dict) else {}
    devices = cuda.get("devices") if isinstance(cuda.get("devices"), list) else []
    first_device = devices[0] if devices and isinstance(devices[0], dict) else {}
    cuda_available = cuda.get("available") is True
    memory_gb = first_device.get("total_memory_gb", 0)
    try:
        vram_bytes = max(0, int(float(memory_gb) * 1024**3))
    except (TypeError, ValueError):
        vram_bytes = 0

    machine = platform.machine().lower()
    architecture = "amd64" if machine in {"amd64", "x86_64"} else machine or "unknown"
    windows_version = getattr(sys, "getwindowsversion", None)
    windows_build = int(windows_version().build) if callable(windows_version) else 0
    comfyui = report.get("comfyui") if isinstance(report.get("comfyui"), dict) else {}
    local_state = _bootstrap_local_state(paths, manifest)
    return BootstrapFacts(
        platform=sys.platform,
        architecture=architecture,
        gpu_vendor="nvidia" if cuda_available else "unknown",
        gpu_generation=_gpu_generation(first_device.get("name")) if cuda_available else "unknown",
        vram_bytes=vram_bytes,
        windows_build=windows_build,
        free_disk_bytes=shutil.disk_usage(_disk_usage_parent(paths.install)).free,
        network_allowed=True,
        endpoint_ready=bool(comfyui.get("available")),
        portable_status=str(local_state["portable_status"]),
        model_status=str(local_state["model_status"]),
    )


def _bootstrap_plan_report(plan: BootstrapPlan, manifest: BootstrapManifest, client: str) -> dict[str, object]:
    next_action = (
        f"local-gpu-imagegen bootstrap apply --plan-id {plan.plan_id} --confirmation {plan.confirmation}"
        if plan.confirmation is not None
        else "local-gpu-imagegen bootstrap status"
    )
    return {
        "ok": True,
        "client": client,
        "status": plan.status,
        "reason": plan.reason,
        "plan_id": plan.plan_id,
        "confirmation": plan.confirmation,
        "actions": [
            {"kind": action.kind, "artifact_id": action.artifact_id}
            for action in plan.actions
        ],
        "estimated_download_bytes": plan.required_download_bytes,
        "estimated_disk_bytes": plan.required_disk_bytes,
        "licenses": [
            {
                "artifact_id": artifact.artifact_id,
                "license_id": artifact.license_id,
                "license_url": artifact.license_url,
            }
            for artifact in (manifest.comfyui, manifest.model)
        ],
        "next_action": next_action,
    }


def _bootstrap_error(error: BaseException) -> dict[str, object]:
    code = getattr(error, "code", None)
    return {"ok": False, "error": {"code": code if isinstance(code, str) else "bootstrap_cli_failed"}}


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
    bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Plan or apply the explicit Windows NVIDIA bootstrap transaction.",
    )
    bootstrap_subparsers = bootstrap.add_subparsers(dest="bootstrap_command", required=True)
    bootstrap_subparsers.add_parser("status", help="Show the local bootstrap state without changing it.")
    plan = bootstrap_subparsers.add_parser("plan", help="Display one bootstrap plan and its confirmation.")
    plan.add_argument("--client", choices=("codex",), required=True)
    apply = bootstrap_subparsers.add_parser("apply", help="Apply one previously displayed bootstrap plan.")
    apply.add_argument("--plan-id", required=True)
    apply.add_argument("--confirmation", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "bootstrap":
        paths = default_bootstrap_paths()
        try:
            if args.bootstrap_command == "status":
                manifest = load_bootstrap_manifest(
                    resolve_resource_root() / "profiles" / "bootstrap" / "windows-nvidia.json"
                )
                state = _bootstrap_local_state(paths, manifest)
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "status": state["status"],
                            "reason_codes": state["reason_codes"],
                            "install_root": str(paths.install),
                            "next_action": "local-gpu-imagegen bootstrap plan --client codex",
                        }
                    )
                )
                return 0
            if args.bootstrap_command == "plan":
                manifest = load_bootstrap_manifest(
                    resolve_resource_root() / "profiles" / "bootstrap" / "windows-nvidia.json"
                )
                plan = build_bootstrap_plan(
                    manifest,
                    _collect_bootstrap_facts(paths, manifest),
                    install_root=paths.install,
                    plan_root=paths.plans,
                )
                print(json.dumps(_bootstrap_plan_report(plan, manifest, args.client)))
                return 0
            if args.bootstrap_command == "apply":
                result = apply_bootstrap_plan(
                    args.plan_id,
                    args.confirmation,
                    state_dir=paths.plans,
                )
                status = result.get("status")
                if status in {"installed", "already_installed"} and result.get("ok") is True:
                    print(
                        json.dumps(
                            {
                                "ok": True,
                                "status": status,
                                "next_action": "local-gpu-imagegen setup codex --apply",
                            }
                        )
                    )
                    return 0
                error = result.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "status": status if isinstance(status, str) else "failed",
                            "error": {
                                "code": code if code == "bootstrap_execution_failed" else "bootstrap_apply_failed"
                            },
                        }
                    ),
                    file=sys.stderr,
                )
                return 1
        except (ArtifactError, OSError, RuntimeError, StateError, ValidationError, ValueError) as error:
            print(json.dumps(_bootstrap_error(error)), file=sys.stderr)
            return 1
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
