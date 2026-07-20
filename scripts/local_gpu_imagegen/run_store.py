from __future__ import annotations

import copy
import ctypes
import json
import os
import re
import secrets
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import atomic_write_json, ensure_within
from .errors import ArtifactError, ConflictError


RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")


class RunStore:
    """Own filesystem persistence for one configured visual-asset output root."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = Path(output_root).resolve()

    def create(self, request: dict[str, object]) -> dict[str, object]:
        if not isinstance(request, dict):
            raise ArtifactError("invalid_run_request", "Run requests must be JSON objects.")

        self.output_root.mkdir(parents=True, exist_ok=True)
        runs_root = ensure_within(self.output_root, self.output_root / "runs")
        runs_root.mkdir(parents=True, exist_ok=True)

        for _ in range(10):
            run_id = self._new_run_id()
            run_root = self._run_root(run_id)
            try:
                run_root.mkdir()
            except FileExistsError:
                continue

            manifest: dict[str, object] = {
                "schema_version": 1,
                "run_id": run_id,
                "manifest_revision": 1,
                "state": "created",
                "last_stable_state": "created",
                "active_attempt": None,
                "parent": None,
                "request": copy.deepcopy(request),
                "attempts": [],
                "rounds": [],
                "reviews": [],
                "masks": [],
                "warnings": [],
                "final": None,
            }
            atomic_write_json(self._manifest_path(run_id), manifest)
            return copy.deepcopy(manifest)

        raise ArtifactError("run_id_collision", "Unable to allocate a unique run identifier.")

    def get(self, run_id: str) -> dict[str, object]:
        return self._read_manifest(run_id)

    def update(
        self,
        run_id: str,
        mutator: Callable[[dict[str, object]], object],
    ) -> dict[str, object]:
        run_root = self._run_root(run_id)
        lock_path, owner_token = self._acquire_lock(run_root)
        try:
            manifest = self._read_manifest(run_id)
            mutator(manifest)
            revision = manifest.get("manifest_revision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise ArtifactError("corrupt_manifest", "Manifest revision is invalid.", {"run_id": run_id})
            manifest["manifest_revision"] = revision + 1
            atomic_write_json(self._manifest_path(run_id), manifest)
            return copy.deepcopy(manifest)
        finally:
            self._release_lock(lock_path, owner_token)

    def cleanup(self, run_id: str, *, scope: str, confirmation: str) -> None:
        if confirmation != run_id:
            raise ArtifactError(
                "cleanup_confirmation_mismatch",
                "Cleanup confirmation must exactly match the run identifier.",
                {"run_id": run_id},
            )
        if scope not in {"all", "intermediates"}:
            raise ArtifactError("invalid_cleanup_scope", "Cleanup scope must be all or intermediates.")

        run_root = self._run_root(run_id)
        lock_path, owner_token = self._acquire_lock(run_root)
        try:
            if scope == "all":
                shutil.rmtree(run_root)
                return

            manifest = self._read_manifest(run_id)
            preserved_paths = {
                self._manifest_path(run_id),
                lock_path,
                *self._final_paths(run_root, manifest),
            }
            self._remove_intermediates(run_root, preserved_paths)
        finally:
            self._release_lock(lock_path, owner_token)

    def _new_run_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{timestamp}-{secrets.token_hex(6)}"

    def _run_root(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ArtifactError("invalid_run_id", "Run identifier has an invalid format.", {"run_id": run_id})
        return ensure_within(self.output_root, self.output_root / "runs" / run_id)

    def _manifest_path(self, run_id: str) -> Path:
        return ensure_within(self.output_root, self._run_root(run_id) / "manifest.json")

    def _read_manifest(self, run_id: str) -> dict[str, object]:
        path = self._manifest_path(run_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ArtifactError("run_not_found", "Run manifest does not exist.", {"run_id": run_id}) from error
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ArtifactError("corrupt_manifest", "Run manifest cannot be read as JSON.", {"run_id": run_id}) from error
        if not isinstance(value, dict):
            raise ArtifactError("corrupt_manifest", "Run manifest must be a JSON object.", {"run_id": run_id})
        return value

    def _acquire_lock(self, run_root: Path) -> tuple[Path, str]:
        if not run_root.is_dir():
            raise ArtifactError("run_not_found", "Run directory does not exist.", {"path": str(run_root)})

        lock_path = ensure_within(self.output_root, run_root / ".run.lock")
        owner_token = secrets.token_hex(16)
        metadata = {
            "owner_pid": os.getpid(),
            "owner_token": owner_token,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        while True:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._lock_has_live_owner(lock_path):
                    raise ConflictError("run_busy", "Run is locked by a live owner.", {"run_root": str(run_root)})
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    continue
                except OSError as error:
                    raise ConflictError("run_busy", "Run lock cannot be reclaimed.", {"run_root": str(run_root)}) from error
                continue

            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(metadata, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                raise
            return lock_path, owner_token

    def _lock_has_live_owner(self, lock_path: Path) -> bool:
        try:
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return True
        if not isinstance(metadata, dict):
            return True
        owner_pid = metadata.get("owner_pid")
        if not isinstance(owner_pid, int) or isinstance(owner_pid, bool) or owner_pid <= 0:
            return True
        if os.name == "nt":
            return self._windows_pid_is_live(owner_pid)
        try:
            os.kill(owner_pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True

    def _windows_pid_is_live(self, owner_pid: int) -> bool:
        process_query_limited_information = 0x1000
        access_denied = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
        open_process.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (ctypes.c_void_p,)
        close_handle.restype = ctypes.c_bool

        handle = open_process(process_query_limited_information, False, owner_pid)
        if handle:
            close_handle(handle)
            return True
        return ctypes.get_last_error() == access_denied

    def _release_lock(self, lock_path: Path, owner_token: str) -> None:
        try:
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
            return
        if isinstance(metadata, dict) and metadata.get("owner_token") == owner_token:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def _final_paths(self, run_root: Path, manifest: dict[str, object]) -> set[Path]:
        final = manifest.get("final")
        if isinstance(final, str):
            path_value = final
        elif isinstance(final, dict) and isinstance(final.get("path"), str):
            path_value = final["path"]
        else:
            return set()

        candidate = Path(path_value)
        if not candidate.is_absolute():
            candidate = run_root / candidate
        resolved = ensure_within(self.output_root, candidate)
        if resolved != run_root and run_root not in resolved.parents:
            raise ArtifactError(
                "path_outside_output_root",
                "Final artifact path escapes its run directory.",
                {"path": str(resolved)},
            )
        return {resolved}

    def _remove_intermediates(self, run_root: Path, preserved_paths: set[Path]) -> None:
        def is_preserved(path: Path) -> bool:
            return any(path == preserved or path in preserved.parents for preserved in preserved_paths)

        for path in sorted(run_root.rglob("*"), key=lambda value: len(value.parts), reverse=True):
            if is_preserved(path):
                continue
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
