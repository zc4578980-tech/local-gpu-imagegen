from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .backends.comfyui import ComfyUIAdapter
from .errors import AssetEngineError
from .run_store import is_process_alive, process_identity
from .trust_registry import default_state_dir


DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_START_TIMEOUT_SECONDS = 120.0
MAX_START_TIMEOUT_SECONDS = 300.0
STARTUP_LOCK_OWNER_GRACE_SECONDS = 2.0


class BackendLifecycleError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        details: dict[str, object] | None = None,
        recoverable_next_actions: list[str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}
        self.recoverable_next_actions = recoverable_next_actions or []


@dataclass(frozen=True, slots=True)
class ComfyUIStartConfig:
    root: Path
    base_url: str
    host: str
    port: int
    timeout_seconds: float
    python_executable: Path
    main_script: Path

    @property
    def command(self) -> tuple[str, ...]:
        return (
            str(self.python_executable),
            "-s",
            str(self.main_script),
            "--windows-standalone-build",
            "--listen",
            self.host,
            "--port",
            str(self.port),
            "--disable-auto-launch",
        )


def build_comfyui_start_config(
    root: str | os.PathLike[str],
    *,
    base_url: str = DEFAULT_COMFYUI_URL,
    timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
) -> ComfyUIStartConfig:
    if not isinstance(base_url, str):
        raise BackendLifecycleError("invalid_comfyui_autostart_url")
    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise BackendLifecycleError("invalid_comfyui_autostart_url") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BackendLifecycleError("comfyui_autostart_requires_loopback_http")
    port = 8188 if port is None else port
    if not 1 <= port <= 65535:
        raise BackendLifecycleError("invalid_comfyui_autostart_port")
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not 1 <= float(timeout_seconds) <= MAX_START_TIMEOUT_SECONDS
    ):
        raise BackendLifecycleError("invalid_comfyui_autostart_timeout")

    try:
        resolved_root = Path(root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BackendLifecycleError("comfyui_autostart_root_not_found") from exc
    if not resolved_root.is_dir():
        raise BackendLifecycleError("comfyui_autostart_root_not_directory")
    python_executable = resolved_root / "python_embeded" / "python.exe"
    main_script = resolved_root / "ComfyUI" / "main.py"
    for path, code in (
        (python_executable, "comfyui_autostart_python_not_found"),
        (main_script, "comfyui_autostart_main_not_found"),
    ):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise BackendLifecycleError(code) from exc
        if not resolved.is_file():
            raise BackendLifecycleError(code)
        if path == python_executable:
            python_executable = resolved
        else:
            main_script = resolved

    return ComfyUIStartConfig(
        root=resolved_root,
        base_url=f"http://127.0.0.1:{port}",
        host="127.0.0.1",
        port=port,
        timeout_seconds=float(timeout_seconds),
        python_executable=python_executable,
        main_script=main_script,
    )


def probe_comfyui(base_url: str, timeout: float = 1.0) -> dict[str, object]:
    try:
        adapter = ComfyUIAdapter(base_url, timeout=timeout)
        backend = adapter.probe()
        queue = adapter.client.get_json("/queue")
        if not isinstance(queue, dict):
            raise BackendLifecycleError("invalid_comfyui_queue_response")
        running = queue.get("queue_running")
        pending = queue.get("queue_pending")
        if not isinstance(running, list) or not isinstance(pending, list):
            raise BackendLifecycleError("invalid_comfyui_queue_response")
        return {
            "available": True,
            "backend": backend,
            "queue_running": len(running),
            "queue_pending": len(pending),
        }
    except (AssetEngineError, BackendLifecycleError) as exc:
        return {
            "available": False,
            "error": getattr(exc, "code", str(exc)),
            "queue_running": None,
            "queue_pending": None,
        }


ProcessFactory = Callable[..., Any]
Probe = Callable[[str, float], dict[str, object]]


class ComfyUIProcessSupervisor:
    def __init__(
        self,
        config: ComfyUIStartConfig,
        *,
        process_factory: ProcessFactory = subprocess.Popen,
        probe: Probe = probe_comfyui,
        state_dir: Path | None = None,
        platform_name: str = os.name,
        environ: MutableMapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self.process_factory = process_factory
        self.probe = probe
        self.state_dir = default_state_dir() if state_dir is None else Path(state_dir)
        self.platform_name = platform_name
        self.environ = os.environ if environ is None else environ
        self.process: Any | None = None
        self.stdout_log: Path | None = None
        self.stderr_log: Path | None = None
        self.status = "not_started"
        self.cleanup_status = "not_required"
        self._previous_environment: dict[str, str | None] = {}

    def start(self) -> dict[str, object]:
        if self.status != "not_started":
            raise BackendLifecycleError("comfyui_autostart_already_started")
        if self.platform_name != "nt":
            raise BackendLifecycleError("comfyui_windows_portable_required")
        self._set_environment()
        try:
            readiness = self.probe(self.config.base_url, 1.0)
        except Exception:
            self._restore_environment()
            raise
        if readiness.get("available") is True:
            self.status = "reused_existing"
            return self.report(readiness)

        try:
            lock_dir = self._startup_lock_dir()
        except BackendLifecycleError:
            self._restore_environment()
            raise
        deadline = time.monotonic() + self.config.timeout_seconds
        waited_for_owner = False
        owner_token = secrets.token_hex(16)
        while True:
            try:
                lock_dir.mkdir(parents=False)
                break
            except FileExistsError:
                waited_for_owner = True
                readiness = self.probe(self.config.base_url, 1.0)
                if readiness.get("available") is True:
                    self.status = "waited_for_existing"
                    return self.report(readiness)
                if self._reclaim_stale_startup_lock(lock_dir):
                    continue
                if time.monotonic() >= deadline:
                    self.status = "startup_conflict"
                    self._restore_environment()
                    raise BackendLifecycleError(
                        "startup_conflict",
                        details={"base_url": self.config.base_url},
                        recoverable_next_actions=["retry_after_other_startup"],
                    )
                time.sleep(0.05)
            except OSError as exc:
                self.status = "launch_failed"
                self._restore_environment()
                raise BackendLifecycleError("comfyui_autostart_lock_unavailable") from exc

        try:
            (lock_dir / "owner.json").write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "process_identity": process_identity(os.getpid()),
                        "owner_token": owner_token,
                        "base_url": self.config.base_url,
                    }
                ),
                encoding="utf-8",
            )
            readiness = self.probe(self.config.base_url, 1.0)
            if readiness.get("available") is True:
                self.status = (
                    "waited_for_existing" if waited_for_owner else "reused_existing"
                )
                return self.report(readiness)
            return self._launch_and_wait(deadline, readiness)
        finally:
            self._release_startup_lock(lock_dir, owner_token)

    def _launch_and_wait(
        self,
        deadline: float,
        readiness: dict[str, object],
    ) -> dict[str, object]:

        log_dir = self.state_dir / "backend-logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.status = "launch_failed"
            self._restore_environment()
            raise BackendLifecycleError("comfyui_autostart_log_unavailable") from exc
        stamp = (
            time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            + f"-{os.getpid()}-{time.time_ns()}"
        )
        self.stdout_log = log_dir / f"comfyui-{stamp}.stdout.log"
        self.stderr_log = log_dir / f"comfyui-{stamp}.stderr.log"
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        try:
            with (
                self.stdout_log.open("ab", buffering=0) as stdout,
                self.stderr_log.open("ab", buffering=0) as stderr,
            ):
                self.process = self.process_factory(
                    list(self.config.command),
                    cwd=str(self.config.root),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=creationflags,
                )
        except OSError as exc:
            self.status = "launch_failed"
            self._restore_environment()
            raise BackendLifecycleError("comfyui_autostart_launch_failed") from exc
        self.status = "starting"
        while True:
            returncode = self.process.poll()
            if returncode is not None:
                summary = self._stderr_summary()
                conflict = (
                    "already in use" in summary.lower()
                    or "could not acquire lock" in summary.lower()
                )
                if conflict:
                    readiness = self.probe(self.config.base_url, 1.0)
                    if readiness.get("available") is True:
                        self.process = None
                        self.status = "reused_after_startup_conflict"
                        return self.report(readiness)
                self.status = "startup_conflict" if conflict else "startup_process_exited"
                self._restore_environment()
                code = "startup_conflict" if conflict else "startup_process_exited"
                raise BackendLifecycleError(
                    code,
                    details={
                        "base_url": self.config.base_url,
                        "returncode": returncode,
                        "stderr_summary": summary,
                    },
                    recoverable_next_actions=["inspect_backend_logs", "retry_startup"],
                )
            readiness = self.probe(self.config.base_url, 1.0)
            if readiness.get("available") is True:
                self.status = "started_owned"
                return self.report(readiness)
            if time.monotonic() >= deadline:
                self.status = "endpoint_unreachable"
                cleanup = self._terminate_unhealthy_owned_process()
                self._restore_environment()
                raise BackendLifecycleError(
                    "endpoint_unreachable",
                    details={
                        "base_url": self.config.base_url,
                        "cleanup_status": cleanup,
                    },
                    recoverable_next_actions=["inspect_backend_logs", "retry_startup"],
                )
            time.sleep(0.05)

    def _terminate_unhealthy_owned_process(self) -> str:
        if self.process is None or self.process.poll() is not None:
            return "already_exited"
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return "terminate_failed"
        return "stopped_unhealthy_owned_process"

    def _startup_lock_dir(self) -> Path:
        lock_root = self.state_dir / "backend-start-locks"
        try:
            lock_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackendLifecycleError("comfyui_autostart_lock_unavailable") from exc
        identity = f"{os.path.normcase(str(self.config.root))}\n{self.config.base_url}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return lock_root / f"comfyui-{digest}.lock"

    def _stderr_summary(self, max_bytes: int = 4096) -> str:
        if self.stderr_log is None:
            return ""
        try:
            with self.stderr_log.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - max_bytes))
                return stream.read(max_bytes).decode("utf-8", errors="replace").strip()
        except OSError:
            return ""

    def _read_startup_lock_owner(self, lock_dir: Path) -> dict[str, object] | None:
        try:
            value = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        pid = value.get("pid")
        token = value.get("owner_token")
        identity = value.get("process_identity")
        if (
            not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid <= 0
            or not isinstance(token, str)
            or not token
            or (identity is not None and not isinstance(identity, str))
        ):
            return None
        return value

    def _reclaim_stale_startup_lock(self, lock_dir: Path) -> bool:
        owner = self._read_startup_lock_owner(lock_dir)
        if owner is None:
            try:
                age = time.time() - lock_dir.stat().st_mtime
            except (FileNotFoundError, OSError):
                return True
            if age < STARTUP_LOCK_OWNER_GRACE_SECONDS:
                return False
            return self._claim_startup_lock_as_stale(lock_dir)
        pid = int(owner["pid"])
        if is_process_alive(pid):
            recorded_identity = owner.get("process_identity")
            current_identity = process_identity(pid)
            if not isinstance(recorded_identity, str) or current_identity is None:
                return False
            if recorded_identity == current_identity:
                return False
        return self._claim_startup_lock_as_stale(lock_dir)

    def _claim_startup_lock_as_stale(self, lock_dir: Path) -> bool:
        stale = lock_dir.with_name(
            f"{lock_dir.name}.stale.{secrets.token_hex(16)}"
        )
        try:
            lock_dir.rename(stale)
        except (FileNotFoundError, FileExistsError):
            return True
        except OSError:
            return False
        shutil.rmtree(stale, ignore_errors=True)
        return True

    def _release_startup_lock(self, lock_dir: Path, owner_token: str) -> None:
        owner = self._read_startup_lock_owner(lock_dir)
        if owner is None or owner.get("owner_token") != owner_token:
            return
        try:
            (lock_dir / "owner.json").unlink()
            lock_dir.rmdir()
        except (FileNotFoundError, OSError):
            pass

    def close(self) -> dict[str, object]:
        try:
            if self.process is None:
                self.cleanup_status = "not_owned"
                return self.report()
            if self.process.poll() is not None:
                self.cleanup_status = "already_exited"
                return self.report()
            readiness = self.probe(self.config.base_url, 1.0)
            queue_is_known_empty = (
                readiness.get("available") is True
                and readiness.get("queue_running") == 0
                and readiness.get("queue_pending") == 0
            )
            if not queue_is_known_empty:
                self.cleanup_status = (
                    "retained_nonempty_queue"
                    if readiness.get("available") is True
                    else "retained_unknown_queue"
                )
                return self.report(readiness)
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.cleanup_status = "terminate_timeout"
                return self.report(readiness)
            self.cleanup_status = "stopped_owned_process"
            return self.report(readiness)
        finally:
            self._restore_environment()

    def report(self, readiness: dict[str, object] | None = None) -> dict[str, object]:
        return {
            "status": self.status,
            "cleanup_status": self.cleanup_status,
            "owned_pid": getattr(self.process, "pid", None),
            "base_url": self.config.base_url,
            "command": list(self.config.command),
            "stdout_log": str(self.stdout_log) if self.stdout_log else None,
            "stderr_log": str(self.stderr_log) if self.stderr_log else None,
            "readiness": readiness,
        }

    def _set_environment(self) -> None:
        if not hasattr(self.environ, "__setitem__"):
            raise BackendLifecycleError("comfyui_autostart_environment_not_mutable")
        values = {
            "LOCAL_GPU_IMAGEGEN_COMFYUI_URL": self.config.base_url,
            "LOCAL_GPU_IMAGEGEN_COMFYUI_STARTUP_WAIT_SECONDS": str(
                self.config.timeout_seconds
            ),
            "LOCAL_GPU_IMAGEGEN_COMFYUI_MANAGED": "1",
        }
        for key, value in values.items():
            self._previous_environment[key] = self.environ.get(key)
            self.environ[key] = value

    def _restore_environment(self) -> None:
        if not self._previous_environment:
            return
        for key, value in self._previous_environment.items():
            if value is None:
                self.environ.pop(key, None)
            else:
                self.environ[key] = value
        self._previous_environment.clear()
