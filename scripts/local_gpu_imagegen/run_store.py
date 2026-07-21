from __future__ import annotations

import copy
import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import atomic_write_json, ensure_within, sha256_file, validate_json_serializable
from .errors import ArtifactError, AssetEngineError, ConflictError, StateError, ValidationError
from .visual_review import review_is_eligible, validate_visual_checks, visual_checks_pass


RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AttemptHandle:
    run_id: str
    idempotency_key: str
    request_hash: str
    status: str
    owner_token: str | None = None
    existing_round: dict[str, object] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_hash(value: dict[str, object]) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ValidationError("invalid_attempt_request", "Attempt request must be JSON serializable.") from error
    return hashlib.sha256(encoded).hexdigest()


def is_process_alive(pid: int) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _windows_process_is_alive(pid: int) -> bool:
    process_query_limited_information = 0x1000
    invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
    open_process.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool

    handle = open_process(process_query_limited_information, False, pid)
    if handle:
        close_handle(handle)
        return True
    return ctypes.get_last_error() != invalid_parameter


def process_identity(pid: int) -> str | None:
    """Return a process-start identity, or None when it cannot be queried safely."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_identity(pid)
    return _posix_process_identity(pid)


def _windows_process_identity(pid: int) -> str | None:
    class FileTime(ctypes.Structure):
        _fields_ = (("low", ctypes.c_ulong), ("high", ctypes.c_ulong))

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
    open_process.restype = ctypes.c_void_p
    get_process_times = kernel32.GetProcessTimes
    get_process_times.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    )
    get_process_times.restype = ctypes.c_bool
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool

    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        creation = FileTime()
        exit_time = FileTime()
        kernel_time = FileTime()
        user_time = FileTime()
        if not get_process_times(handle, creation, exit_time, kernel_time, user_time):
            return None
        creation_ticks = (creation.high << 32) | creation.low
        return f"windows-filetime:{creation_ticks}"
    finally:
        close_handle(handle)


def _posix_process_identity(pid: int) -> str | None:
    try:
        stat_text = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        closing_parenthesis = stat_text.rfind(")")
        if closing_parenthesis < 0:
            return None
        fields_after_command = stat_text[closing_parenthesis + 2 :].split()
        start_ticks = fields_after_command[19]
    except (FileNotFoundError, IndexError, OSError, UnicodeDecodeError):
        return None

    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        boot_id = "unknown-boot"
    return f"posix-proc:{boot_id}:{start_ticks}"


class RunStore:
    """Own filesystem persistence for one configured visual-asset output root."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = Path(output_root).resolve()

    def create(self, request: dict[str, object]) -> dict[str, object]:
        if not isinstance(request, dict):
            raise ArtifactError("invalid_run_request", "Run requests must be JSON objects.")
        validate_json_serializable(request)

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
        manifest = self._read_manifest(run_id)
        active_attempt = manifest.get("active_attempt")
        if not isinstance(active_attempt, dict) or active_attempt.get("status") != "running":
            return copy.deepcopy(manifest)
        return self._recover_stale_attempt(run_id, manifest)

    def run_root(self, run_id: str) -> Path:
        """Return the validated filesystem root for an existing run."""
        self.get(run_id)
        return self._run_root(run_id)

    def begin_attempt(self, run_id: str, idempotency_key: str, request: dict[str, object]) -> AttemptHandle:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError("invalid_idempotency_key", "Idempotency key must be a non-empty string.")
        if not isinstance(request, dict):
            raise ValidationError("invalid_attempt_request", "Attempt request must be an object.")
        validate_json_serializable(request)
        normalized_request = self._normalize_attempt_request(request)
        request_hash_value = request_hash(normalized_request)
        legacy_request_hash_value = request_hash({
            "action": normalized_request["action"],
            "seed": normalized_request["seed"],
            "plan": normalized_request["generation_plan"],
        })

        manifest = self.get(run_id)
        existing = self._find_idempotent_attempt(
            manifest,
            idempotency_key,
            request_hash_value,
            legacy_request_hash_value,
        )
        if existing is not None:
            status, value = existing
            if status == "completed":
                return AttemptHandle(
                    run_id, idempotency_key, request_hash_value, "completed",
                    existing_round=copy.deepcopy(value),
                )
            if status == "busy":
                return AttemptHandle(run_id, idempotency_key, request_hash_value, "busy")

        active_attempt = manifest.get("active_attempt")
        if isinstance(active_attempt, dict) and active_attempt.get("status") == "running":
            raise ConflictError("run_busy", "Run already has a live generation attempt.", {"run_id": run_id})

        self._validate_attempt_transition(manifest, normalized_request)

        run_root = self._run_root(run_id)
        try:
            lock_path, owner_token = self._acquire_lock(run_root)
        except ConflictError as error:
            if error.code != "run_busy":
                raise
            current = self._read_manifest(run_id)
            raced = self._find_idempotent_attempt(
                current,
                idempotency_key,
                request_hash_value,
                legacy_request_hash_value,
            )
            if raced is not None:
                return self._attempt_handle(run_id, idempotency_key, request_hash_value, raced)
            raise

        retain_lock = False
        try:
            current = self._read_manifest(run_id)
            raced = self._find_idempotent_attempt(
                current,
                idempotency_key,
                request_hash_value,
                legacy_request_hash_value,
            )
            if raced is not None:
                return self._attempt_handle(run_id, idempotency_key, request_hash_value, raced)
            active_attempt = current.get("active_attempt")
            if isinstance(active_attempt, dict) and active_attempt.get("status") == "running":
                raise ConflictError("run_busy", "Run already has a live generation attempt.", {"run_id": run_id})
            self._validate_attempt_transition(current, normalized_request)
            resumable = self._find_resumable_attempt(
                current,
                idempotency_key,
                request_hash_value,
                legacy_request_hash_value,
            )

            active: dict[str, object] = {
                "idempotency_key": idempotency_key,
                "request_hash": request_hash_value,
                "action": normalized_request["action"],
                "seed": normalized_request["seed"],
                "generation_plan": copy.deepcopy(normalized_request["generation_plan"]),
                "change_summary": normalized_request["change_summary"],
                "status": "running",
                "started_at": utc_now(),
            }
            for field in ("route", "compiled_prompt"):
                if field in normalized_request:
                    active[field] = copy.deepcopy(normalized_request[field])
            if "mask_id" in normalized_request:
                active["mask_id"] = normalized_request["mask_id"]
            status = "started"
            existing_round = None
            if resumable is not None:
                image = copy.deepcopy(resumable["image"])
                active["image"] = image
                if isinstance(resumable.get("backend_result"), dict):
                    active["backend_result"] = copy.deepcopy(resumable["backend_result"])
                status = "resume_preview"
                existing_round = {
                    "round_number": len(self._rounds(current)) + 1,
                    "image": copy.deepcopy(image),
                }
                if "backend_result" in active:
                    existing_round["backend_result"] = copy.deepcopy(active["backend_result"])

            current["active_attempt"] = active
            current["state"] = "generating"
            self._save_manifest(run_id, current)
            retain_lock = True
            return AttemptHandle(
                run_id,
                idempotency_key,
                request_hash_value,
                status,
                owner_token,
                existing_round,
            )
        finally:
            if not retain_lock:
                self._release_lock(lock_path, owner_token)

    def complete_attempt(self, handle: AttemptHandle, result: dict[str, object]) -> dict[str, object]:
        self._require_attempt_handle(handle)
        if not isinstance(result, dict):
            raise ValidationError("invalid_attempt_result", "Attempt result must be an object.")
        validate_json_serializable(result)
        lock_path = self._lock_path(handle.run_id)
        owns_attempt = False
        try:
            manifest, active = self._owned_attempt(handle)
            owns_attempt = True
            rounds = self._rounds(manifest)
            round_number = len(rounds) + 1
            round_value = copy.deepcopy(result)
            if "image" in active:
                round_value["image"] = copy.deepcopy(active["image"])
            if "backend_result" in active:
                round_value["backend_result"] = copy.deepcopy(active["backend_result"])
            round_value.update({
                "round_number": round_number,
                "status": "generated",
                "idempotency_key": handle.idempotency_key,
                "request_hash": handle.request_hash,
                "action": active["action"],
                "seed": active["seed"],
                "generation_plan": copy.deepcopy(active["generation_plan"]),
                "change_summary": active["change_summary"],
            })
            for field in ("route", "compiled_prompt"):
                if field in active:
                    round_value[field] = copy.deepcopy(active[field])
            if "mask_id" in active:
                round_value["mask_id"] = active["mask_id"]
            rounds.append(round_value)

            archived = copy.deepcopy(active)
            archived["status"] = "completed"
            archived["completed_at"] = utc_now()
            archived["round_number"] = round_number
            self._attempts(manifest).append(archived)
            manifest["active_attempt"] = None
            manifest["state"] = "generated"
            manifest["last_stable_state"] = "generated"
            return self._save_manifest(handle.run_id, manifest)
        finally:
            if owns_attempt and handle.owner_token is not None:
                self._release_lock(lock_path, handle.owner_token)

    def mark_attempt_image(
        self,
        handle: AttemptHandle,
        image: dict[str, object],
        backend_result: dict[str, object] | None = None,
    ) -> dict[str, object]:
        manifest, active = self._owned_attempt(handle)
        active["image"] = self._validate_full_image(handle.run_id, image)
        if backend_result is not None:
            if not isinstance(backend_result, dict):
                raise ValidationError("invalid_backend_result", "Backend result metadata must be an object.")
            validate_json_serializable(backend_result)
            active["backend_result"] = copy.deepcopy(backend_result)
        manifest["active_attempt"] = active
        return self._save_manifest(handle.run_id, manifest)

    def fail_attempt(self, handle: AttemptHandle, error: dict[str, object]) -> dict[str, object]:
        self._require_attempt_handle(handle)
        if not isinstance(error, dict):
            raise ValidationError("invalid_attempt_error", "Attempt error must be an object.")
        validate_json_serializable(error)
        lock_path = self._lock_path(handle.run_id)
        owns_attempt = False
        try:
            manifest, active = self._owned_attempt(handle)
            owns_attempt = True
            archived = copy.deepcopy(active)
            archived["status"] = "failed"
            archived["failed_at"] = utc_now()
            archived["error"] = copy.deepcopy(error)
            self._attempts(manifest).append(archived)
            manifest["active_attempt"] = None
            manifest["state"] = manifest["last_stable_state"]
            return self._save_manifest(handle.run_id, manifest)
        finally:
            if owns_attempt and handle.owner_token is not None:
                self._release_lock(lock_path, handle.owner_token)

    def record_review(self, run_id: str, round_number: int, review: dict[str, object]) -> dict[str, object]:
        if not isinstance(review, dict):
            raise ValidationError("invalid_review", "Review must be an object.")
        validate_json_serializable(review)

        def add_review(manifest: dict[str, object]) -> None:
            self._validate_review(manifest, round_number, review)
            review_value = copy.deepcopy(review)
            review_value["round_number"] = round_number
            review_value["reviewed_at"] = utc_now()
            self._reviews(manifest).append(review_value)
            manifest["state"] = "reviewed"
            manifest["last_stable_state"] = "reviewed"

        return self.update(run_id, add_review)

    def finalize(self, run_id: str, round_number: int, summary: str) -> dict[str, object]:
        self._validate_final_summary(summary)

        def select_round(manifest: dict[str, object]) -> None:
            self._select_final_round(manifest, round_number, summary)

        return self.update(run_id, select_round)

    def finalize_published(
        self,
        run_id: str,
        round_number: int,
        summary: str,
        final_image: dict[str, object],
        publish: Callable[[], object],
        rollback: Callable[[], object],
        commit: Callable[[], object] | None = None,
    ) -> dict[str, object]:
        """Publish a final file and manifest under one run-lock ownership."""
        self._validate_final_summary(summary)
        if not isinstance(final_image, dict):
            raise ValidationError("invalid_image_metadata", "Final image metadata must be an object.")
        validate_json_serializable(final_image)
        if not callable(publish) or not callable(rollback) or commit is not None and not callable(commit):
            raise ValidationError("invalid_final_publisher", "Final publication callbacks must be callable.")

        run_root = self._run_root(run_id)
        lock_path, owner_token = self._acquire_lock(run_root)
        published = False
        try:
            manifest = self._read_manifest(run_id)
            self._select_final_round(manifest, round_number, summary)
            try:
                published = True
                publish()
                validated_image = self._validate_full_image(run_id, final_image)
                final = manifest.get("final")
                if not isinstance(final, dict):
                    raise ArtifactError("corrupt_manifest", "Final selection metadata is missing.")
                final["image"] = copy.deepcopy(validated_image)
                final["path"] = validated_image["path"]
                revision = manifest.get("manifest_revision")
                if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                    raise ArtifactError("corrupt_manifest", "Manifest revision is invalid.", {"run_id": run_id})
                manifest["manifest_revision"] = revision + 1
                atomic_write_json(self._manifest_path(run_id), manifest)
            except Exception:
                if published:
                    rollback()
                raise
            return self._finalize_result_after_commit(manifest, commit)
        finally:
            self._release_lock(lock_path, owner_token)

    def finalize_round_published(
        self,
        run_id: str,
        round_number: int,
        summary: str,
        publish: Callable[[dict[str, object]], dict[str, object]],
        rollback: Callable[[], object],
        commit: Callable[[], object] | None = None,
        decorate_manifest: Callable[[dict[str, object]], object] | None = None,
    ) -> dict[str, object]:
        """Validate and publish the caller-nominated reviewed round under one run lock."""
        self._validate_final_summary(summary)
        if (
            not callable(publish)
            or not callable(rollback)
            or commit is not None and not callable(commit)
            or decorate_manifest is not None and not callable(decorate_manifest)
        ):
            raise ValidationError("invalid_final_publisher", "Final publication callbacks must be callable.")

        run_root = self._run_root(run_id)
        lock_path, owner_token = self._acquire_lock(run_root)
        published = False
        try:
            manifest = self._read_manifest(run_id)
            self._select_final_round(manifest, round_number, summary)
            selected = self._round_by_number(manifest, round_number)
            if selected is None:
                raise ArtifactError("corrupt_manifest", "Finalized round disappeared from the locked manifest.")
            try:
                published = True
                final_image = publish(copy.deepcopy(selected))
                validated_image = self._validate_full_image(run_id, final_image)
                final = manifest.get("final")
                if not isinstance(final, dict):
                    raise ArtifactError("corrupt_manifest", "Final selection metadata is missing.")
                final["image"] = copy.deepcopy(validated_image)
                final["path"] = validated_image["path"]
                if decorate_manifest is not None:
                    decorate_manifest(manifest)
                validate_json_serializable(manifest)
                revision = manifest.get("manifest_revision")
                if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                    raise ArtifactError("corrupt_manifest", "Manifest revision is invalid.", {"run_id": run_id})
                manifest["manifest_revision"] = revision + 1
                atomic_write_json(self._manifest_path(run_id), manifest)
            except Exception:
                if published:
                    rollback()
                raise
            return self._finalize_result_after_commit(manifest, commit)
        finally:
            self._release_lock(lock_path, owner_token)

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
            manifest = self._read_manifest(run_id)
            if scope == "all":
                shutil.rmtree(run_root)
                return

            if manifest.get("state") != "finalized" or manifest.get("final") is None:
                raise StateError(
                    "run_not_finalized",
                    "Intermediate cleanup is allowed only after finalization.",
                    {"run_id": run_id},
                )
            final_paths = self._final_paths(run_root, manifest)
            started_at = utc_now()
            self._prune_intermediate_references(manifest, started_at)
            manifest["intermediate_cleanup"] = {"status": "pending", "started_at": started_at}
            manifest.pop("intermediates_cleaned_at", None)
            manifest = self._save_manifest(run_id, manifest)
            preserved_paths = {
                self._manifest_path(run_id),
                lock_path,
                *final_paths,
            }
            self._remove_intermediates(run_root, preserved_paths)
            completed_at = utc_now()
            manifest["intermediate_cleanup"] = {
                "status": "completed",
                "started_at": started_at,
                "completed_at": completed_at,
            }
            manifest["intermediates_cleaned_at"] = completed_at
            self._save_manifest(run_id, manifest)
        finally:
            self._release_lock(lock_path, owner_token)

    def _new_run_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{timestamp}-{secrets.token_hex(6)}"

    def _run_root(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ArtifactError("invalid_run_id", "Run identifier has an invalid format.", {"run_id": run_id})
        runs_root = self.output_root / "runs"
        candidate = runs_root / run_id
        self._reject_run_directory_aliases(runs_root, candidate)
        return ensure_within(self.output_root, candidate)

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
        if value.get("run_id") != run_id:
            raise ArtifactError(
                "manifest_run_id_mismatch",
                "Run manifest identity does not match the requested run.",
                {"run_id": run_id, "manifest_run_id": value.get("run_id")},
            )
        return value

    def _acquire_lock(self, run_root: Path) -> tuple[Path, str]:
        try:
            return self._acquire_lock_impl(run_root)
        except AssetEngineError:
            raise
        except OSError as error:
            raise ArtifactError(
                "lock_operation_failed",
                "Run lock filesystem operation failed.",
                {"path": str(run_root), "errno": error.errno},
            ) from error

    def _acquire_lock_impl(self, run_root: Path) -> tuple[Path, str]:
        if not run_root.is_dir():
            raise ArtifactError("run_not_found", "Run directory does not exist.", {"path": str(run_root)})

        lock_path = ensure_within(self.output_root, run_root / ".run.lock")
        owner_token = secrets.token_hex(16)
        pending_path = ensure_within(self.output_root, run_root / f".run.lock.{owner_token}.tmp")
        owner_pid = os.getpid()
        metadata = {
            "owner_pid": owner_pid,
            "owner_token": owner_token,
            "owner_process_identity": process_identity(owner_pid),
            "created_at": utc_now(),
        }
        try:
            descriptor = os.open(pending_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(metadata, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                try:
                    pending_path.unlink()
                except FileNotFoundError:
                    pass
                raise

            while True:
                try:
                    os.link(pending_path, lock_path)
                except FileExistsError:
                    if self._lock_has_live_owner(lock_path, ignored_pending_token=owner_token):
                        raise ConflictError("run_busy", "Run is locked by a live owner.", {"run_root": str(run_root)})
                    stale_path = self._claim_stale_lock(
                        lock_path,
                        run_root.name,
                        ignored_pending_token=owner_token,
                    )
                    if stale_path is not None:
                        try:
                            stale_path.unlink()
                        except FileNotFoundError:
                            pass
                    continue
                except OSError as error:
                    if not self._hard_link_is_unavailable(error):
                        raise ArtifactError(
                            "lock_operation_failed",
                            "Atomic run lock publication failed.",
                            {"path": str(lock_path), "errno": error.errno},
                        ) from error
                    self._publish_lock_exclusive(lock_path, metadata, run_root, owner_token)
                return lock_path, owner_token
        finally:
            try:
                pending_path.unlink()
            except FileNotFoundError:
                pass

    def _publish_lock_exclusive(
        self,
        lock_path: Path,
        metadata: dict[str, object],
        run_root: Path,
        owner_token: str,
    ) -> None:
        while True:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._lock_has_live_owner(lock_path, ignored_pending_token=owner_token):
                    raise ConflictError("run_busy", "Run is locked by a live owner.", {"run_root": str(run_root)})
                stale_path = self._claim_stale_lock(
                    lock_path,
                    run_root.name,
                    ignored_pending_token=owner_token,
                )
                if stale_path is not None:
                    try:
                        stale_path.unlink()
                    except FileNotFoundError:
                        pass
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
            return

    def _hard_link_is_unavailable(self, error: OSError) -> bool:
        unsupported_errnos = {
            errno.EACCES,
            errno.EPERM,
            errno.ENOSYS,
            errno.EXDEV,
            getattr(errno, "ENOTSUP", -1),
            getattr(errno, "EOPNOTSUPP", -1),
        }
        return error.errno in unsupported_errnos or getattr(error, "winerror", None) in {1, 5, 50}

    def _lock_has_live_owner(self, lock_path: Path, *, ignored_pending_token: str | None = None) -> bool:
        metadata = self._read_lock_metadata(lock_path)
        if metadata is not None:
            return self._lock_metadata_has_live_owner(metadata)
        return self._pending_lock_has_live_owner(lock_path.parent, ignored_pending_token)

    def _pending_lock_has_live_owner(self, run_root: Path, ignored_owner_token: str | None = None) -> bool:
        for pending_path in run_root.glob(".run.lock.*.tmp"):
            metadata = self._read_lock_metadata(pending_path)
            if metadata is None or metadata.get("owner_token") == ignored_owner_token:
                continue
            if self._lock_metadata_has_live_owner(metadata):
                return True
        return False

    def _pid_is_live(self, owner_pid: int) -> bool:
        return is_process_alive(owner_pid)

    def _windows_pid_is_live(self, owner_pid: int) -> bool:
        return _windows_process_is_alive(owner_pid)

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

    def _lock_path(self, run_id: str) -> Path:
        return ensure_within(self.output_root, self._run_root(run_id) / ".run.lock")

    def _save_manifest(self, run_id: str, manifest: dict[str, object]) -> dict[str, object]:
        revision = manifest.get("manifest_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ArtifactError("corrupt_manifest", "Manifest revision is invalid.", {"run_id": run_id})
        manifest["manifest_revision"] = revision + 1
        atomic_write_json(self._manifest_path(run_id), manifest)
        return copy.deepcopy(manifest)

    def _find_idempotent_attempt(
        self,
        manifest: dict[str, object],
        idempotency_key: str,
        request_hash_value: str,
        legacy_request_hash_value: str,
    ) -> tuple[str, dict[str, object] | None] | None:
        candidates: list[dict[str, object]] = []
        active = manifest.get("active_attempt")
        if isinstance(active, dict) and active.get("idempotency_key") == idempotency_key:
            candidates.append(active)
        candidates.extend(
            attempt for attempt in reversed(self._attempts(manifest))
            if attempt.get("idempotency_key") == idempotency_key
        )
        for attempt in candidates:
            if not self._attempt_request_hash_matches(
                attempt,
                request_hash_value,
                legacy_request_hash_value,
            ):
                raise ConflictError(
                    "idempotency_conflict",
                    "Idempotency key was already used for a different request.",
                    {"idempotency_key": idempotency_key},
                )
            status = attempt.get("status")
            if status == "running":
                return "busy", None
            if status == "completed":
                if attempt.get("artifacts_cleaned_at") is not None:
                    raise StateError(
                        "run_artifacts_cleaned",
                        "Completed attempt artifacts were removed by intermediate cleanup.",
                        {"idempotency_key": idempotency_key},
                    )
                round_number = attempt.get("round_number")
                if isinstance(round_number, int):
                    existing_round = self._round_by_number(manifest, round_number)
                    if existing_round is not None:
                        if existing_round.get("artifacts_cleaned_at") is not None:
                            raise StateError(
                                "run_artifacts_cleaned",
                                "Completed round artifacts were removed by intermediate cleanup.",
                                {"idempotency_key": idempotency_key},
                            )
                        return "completed", existing_round
        return None

    def _attempt_handle(
        self,
        run_id: str,
        idempotency_key: str,
        request_hash_value: str,
        existing: tuple[str, dict[str, object] | None],
    ) -> AttemptHandle:
        status, value = existing
        return AttemptHandle(
            run_id,
            idempotency_key,
            request_hash_value,
            status,
            existing_round=copy.deepcopy(value),
        )

    def _find_resumable_attempt(
        self,
        manifest: dict[str, object],
        idempotency_key: str,
        request_hash_value: str,
        legacy_request_hash_value: str,
    ) -> dict[str, object] | None:
        run_id = manifest.get("run_id")
        if not isinstance(run_id, str):
            raise ArtifactError("corrupt_manifest", "Manifest run_id must be a string.")
        for attempt in reversed(self._attempts(manifest)):
            if not (
                attempt.get("idempotency_key") == idempotency_key
                and self._attempt_request_hash_matches(
                    attempt,
                    request_hash_value,
                    legacy_request_hash_value,
                )
                and attempt.get("status") == "interrupted"
            ):
                continue
            try:
                self._validate_full_image(run_id, attempt.get("image"))
            except (ArtifactError, ValidationError):
                continue
            return attempt
        return None

    @staticmethod
    def _attempt_request_hash_matches(
        attempt: dict[str, object],
        request_hash_value: str,
        legacy_request_hash_value: str,
    ) -> bool:
        stored_hash = attempt.get("request_hash")
        if stored_hash == request_hash_value:
            return True
        return (
            "generation_plan" not in attempt
            and "change_summary" not in attempt
            and stored_hash == legacy_request_hash_value
        )

    @staticmethod
    def _normalize_attempt_request(request: dict[str, object]) -> dict[str, object]:
        plan = request.get("plan")
        if not isinstance(plan, dict):
            raise ValidationError("invalid_generation_plan", "Attempt generation plan must be an object.")
        change_summary = request.get("change_summary")
        if not isinstance(change_summary, str) or not change_summary.strip() or len(change_summary.strip()) > 2000:
            raise ValidationError(
                "invalid_change_summary",
                "Attempt change_summary must be non-empty and concise.",
            )
        normalized = {
            "action": request.get("action"),
            "seed": request.get("seed"),
            "generation_plan": copy.deepcopy(plan),
            "change_summary": change_summary.strip(),
        }
        for field in ("route", "compiled_prompt"):
            if field in request:
                value = request[field]
                if not isinstance(value, dict):
                    raise ValidationError(
                        "invalid_attempt_request",
                        f"Attempt {field} must be an object.",
                    )
                normalized[field] = copy.deepcopy(value)
        if "mask_id" in request:
            mask_id = request["mask_id"]
            if not isinstance(mask_id, str) or not mask_id.strip():
                raise ValidationError("invalid_mask_id", "Attempt mask_id must be a non-empty string.")
            normalized["mask_id"] = mask_id
        return normalized

    def _validate_attempt_transition(self, manifest: dict[str, object], request: dict[str, object]) -> None:
        if manifest.get("state") == "finalized" or manifest.get("final") is not None:
            raise StateError("run_finalized", "Finalized runs cannot start new generation attempts.")
        action = request.get("action")
        if action not in {"initial", "refine", "explore"}:
            raise ValidationError("invalid_generation_action", "Action must be initial, refine, or explore.")
        seed = request.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValidationError("invalid_seed", "Attempt seed must be an integer.")

        run_request = manifest.get("request")
        if not isinstance(run_request, dict):
            raise ArtifactError("corrupt_manifest", "Manifest request must be an object.")
        max_rounds = run_request.get("max_rounds")
        if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or not 1 <= max_rounds <= 3:
            raise StateError("invalid_round_budget", "Run max_rounds must be an integer from 1 to 3.")
        rounds = self._rounds(manifest)
        if len(rounds) >= max_rounds:
            raise StateError("round_budget_exhausted", "Run has consumed its successful round budget.")
        if not rounds:
            if action != "initial":
                raise StateError("initial_round_required", "The first successful round must use initial action.")
            return
        if action == "initial":
            raise StateError("initial_already_completed", "Initial action is only valid before a successful round.")

        latest = rounds[-1]
        round_number = latest.get("round_number")
        if not isinstance(round_number, int) or not self._round_has_review(manifest, round_number):
            raise StateError("round_requires_review", "Latest successful round must be reviewed first.")
        latest_seed = latest.get("seed")
        if action == "refine" and seed != latest_seed:
            raise StateError("refine_seed_mismatch", "Refine must preserve the latest successful seed.")
        if action == "explore" and seed == latest_seed:
            raise StateError("explore_seed_unchanged", "Explore must use a different seed.")

    @staticmethod
    def _reject_run_directory_aliases(*paths: Path) -> None:
        for path in paths:
            try:
                if _path_is_link_like(path):
                    raise ArtifactError(
                        "unsafe_run_directory",
                        "Run directory components cannot be links, junctions, or reparse points.",
                        {"path": str(path)},
                    )
            except FileNotFoundError:
                continue
            except ArtifactError:
                raise
            except OSError as error:
                raise ArtifactError(
                    "unsafe_run_directory",
                    "Run directory components could not be validated safely.",
                    {"path": str(path), "errno": error.errno},
                ) from error

    def _owned_attempt(self, handle: AttemptHandle) -> tuple[dict[str, object], dict[str, object]]:
        self._require_attempt_handle(handle)
        metadata = self._read_lock_metadata(self._lock_path(handle.run_id))
        if metadata is None or metadata.get("owner_token") != handle.owner_token:
            raise ConflictError("attempt_owner_mismatch", "Attempt handle does not own the active attempt.")
        manifest = self._read_manifest(handle.run_id)
        active = manifest.get("active_attempt")
        if not isinstance(active, dict) or active.get("status") != "running":
            raise ConflictError("stale_attempt_handle", "Attempt handle is no longer active.")
        if (
            active.get("idempotency_key") != handle.idempotency_key
            or active.get("request_hash") != handle.request_hash
        ):
            raise ConflictError("stale_attempt_handle", "Attempt handle does not match the active attempt.")
        return manifest, copy.deepcopy(active)

    def _require_attempt_handle(self, handle: object) -> None:
        if not isinstance(handle, AttemptHandle) or not isinstance(handle.owner_token, str):
            raise ConflictError("attempt_owner_mismatch", "Attempt handle does not own the active attempt.")

    def _validate_full_image(self, run_id: str, image: object) -> dict[str, object]:
        if not self._is_full_image(image):
            raise ValidationError(
                "invalid_image_metadata",
                "Full image metadata requires path, SHA-256, positive width, and positive height.",
            )
        validate_json_serializable(image)
        assert isinstance(image, dict)
        path_value = image["path"]
        assert isinstance(path_value, str)
        relative_path = Path(path_value)
        if relative_path.is_absolute():
            raise ArtifactError("invalid_image_path", "Attempt image path must be relative to its run directory.")
        run_root = self._run_root(run_id)
        resolved = (run_root / relative_path).resolve()
        if resolved == run_root or run_root not in resolved.parents:
            raise ArtifactError(
                "invalid_image_path",
                "Attempt image path escapes its run directory.",
                {"path": path_value},
            )
        if not resolved.is_file():
            raise ArtifactError("image_not_found", "Attempt image must be an existing regular file.", {"path": path_value})
        try:
            actual_digest = sha256_file(resolved)
        except OSError as error:
            raise ArtifactError("image_unreadable", "Attempt image cannot be read.", {"path": path_value}) from error
        if actual_digest != image["sha256"]:
            raise ArtifactError(
                "image_hash_mismatch",
                "Attempt image digest does not match the recorded SHA-256.",
                {"path": path_value},
            )
        return copy.deepcopy(image)

    def _is_full_image(self, image: object) -> bool:
        if not isinstance(image, dict):
            return False
        path = image.get("path")
        digest = image.get("sha256")
        width = image.get("width")
        height = image.get("height")
        return (
            isinstance(path, str)
            and bool(path.strip())
            and isinstance(digest, str)
            and SHA256_PATTERN.fullmatch(digest) is not None
            and isinstance(width, int)
            and not isinstance(width, bool)
            and width > 0
            and isinstance(height, int)
            and not isinstance(height, bool)
            and height > 0
        )

    def _validate_review(
        self,
        manifest: dict[str, object],
        round_number: int,
        review: dict[str, object],
    ) -> None:
        required_fields = {
            "scores",
            "hard_failures",
            "critique",
            "constraint_results",
            "visual_checks",
            "next_action",
        }
        child_run = isinstance(manifest.get("parent"), dict)
        if child_run:
            required_fields.add("preservation_results")
        if set(review) != required_fields:
            raise ValidationError("invalid_review", "Review fields do not match the required structure.")
        if not isinstance(round_number, int) or isinstance(round_number, bool):
            raise ValidationError("invalid_round_number", "Round number must be an integer.")
        if self._round_by_number(manifest, round_number) is None:
            raise StateError("round_not_found", "Reviewed round does not exist.", {"round_number": round_number})
        rounds = self._rounds(manifest)
        if not rounds or rounds[-1].get("round_number") != round_number:
            raise StateError("review_not_latest_round", "Only the latest successful round can be reviewed.")
        if self._round_has_review(manifest, round_number):
            raise StateError("review_already_recorded", "Round already has a review.")
        if manifest.get("active_attempt") is not None:
            raise StateError("run_busy", "Cannot review while an attempt is active.")

        run_request = manifest.get("request")
        if not isinstance(run_request, dict):
            raise ArtifactError("corrupt_manifest", "Manifest request must be an object.")
        profile = run_request.get("merged_profile")
        if not isinstance(profile, dict):
            profile = {}
        rubric = profile.get("rubric", {})
        if not isinstance(rubric, dict):
            raise ArtifactError("corrupt_manifest", "Merged profile rubric must be an object.")
        scores = review.get("scores")
        if not isinstance(scores, dict) or set(scores) != set(rubric):
            raise ValidationError("invalid_review_scores", "Review scores must exactly match rubric dimensions.")
        if any(not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5 for score in scores.values()):
            raise ValidationError("invalid_review_scores", "Review scores must be integers from 1 to 5.")

        registered_failures = profile.get("hard_failures", [])
        hard_failures = review.get("hard_failures")
        dynamic_failures: set[str] = set()
        if child_run:
            dynamic_failures = self._validate_preservation_results(manifest, review, hard_failures)
        if (
            not isinstance(registered_failures, list)
            or not all(isinstance(value, str) for value in registered_failures)
            or not isinstance(hard_failures, list)
            or not all(isinstance(value, str) for value in hard_failures)
            or len(set(hard_failures)) != len(hard_failures)
            or any(value not in registered_failures and value not in dynamic_failures for value in hard_failures)
        ):
            raise ValidationError("invalid_hard_failures", "Review hard failures must be registered unique strings.")

        critique = review.get("critique")
        if not isinstance(critique, str) or not critique.strip() or len(critique.strip()) > 2000:
            raise ValidationError("invalid_review_critique", "Review critique must be non-empty and concise.")
        if review.get("next_action") not in {"refine", "explore", "finalize"}:
            raise ValidationError("invalid_next_action", "Review next_action must be refine, explore, or finalize.")
        visual_checks = validate_visual_checks(review.get("visual_checks"))
        if review.get("next_action") == "finalize" and not visual_checks_pass(visual_checks):
            raise ValidationError(
                "visual_checks_require_revision",
                "Failed or uncertain visual checks cannot request finalization.",
            )

        constraints = run_request.get("constraints", {})
        results = review.get("constraint_results")
        if not isinstance(constraints, dict) or not isinstance(results, dict) or set(results) != set(constraints):
            raise ValidationError("invalid_constraint_results", "Constraint results must exactly match explicit constraints.")
        required_failure = False
        for name, result in results.items():
            if not isinstance(result, dict) or set(result) != {"status", "observation"}:
                raise ValidationError("invalid_constraint_results", "Each constraint result must have status and observation.")
            if result.get("status") not in {"pass", "fail", "uncertain"}:
                raise ValidationError("invalid_constraint_results", "Constraint result status is invalid.")
            observation = result.get("observation")
            if not isinstance(observation, str) or not observation.strip():
                raise ValidationError("invalid_constraint_results", "Constraint observations must be non-empty.")
            specification = constraints[name]
            if (
                result["status"] == "fail"
                and isinstance(specification, dict)
                and specification.get("required") is True
            ):
                required_failure = True
        if required_failure and "explicit_constraint_violation" not in hard_failures:
            raise ValidationError(
                "inconsistent_hard_failures",
                "A failed required constraint requires explicit_constraint_violation.",
            )

    @staticmethod
    def _validate_preservation_results(
        manifest: dict[str, object],
        review: dict[str, object],
        hard_failures: object,
    ) -> set[str]:
        revision = manifest.get("revision")
        contract = revision.get("contract") if isinstance(revision, dict) else None
        preserve = contract.get("preserve") if isinstance(contract, dict) else None
        if not isinstance(preserve, list) or not all(isinstance(item, dict) for item in preserve):
            raise ArtifactError("corrupt_manifest", "Child revision preserve contract is invalid.")
        expected: dict[str, dict[str, object]] = {}
        for item in preserve:
            target = item.get("target")
            strength = item.get("strength")
            if not isinstance(target, str) or strength not in {"hard", "soft"}:
                raise ArtifactError("corrupt_manifest", "Child revision preserve contract is invalid.")
            key = target.casefold()
            if key in expected:
                raise ArtifactError("corrupt_manifest", "Child revision preserve targets are duplicated.")
            expected[key] = item

        results = review.get("preservation_results")
        if not isinstance(results, list) or len(results) != len(expected):
            raise ValidationError(
                "invalid_preservation_results",
                "preservation_results must contain one entry per preserve target.",
            )
        observed: dict[str, str] = {}
        for result in results:
            if not isinstance(result, dict) or set(result) != {"target", "status", "observation"}:
                raise ValidationError(
                    "invalid_preservation_results",
                    "Each preservation result requires target, status, and observation.",
                )
            target = result.get("target")
            status = result.get("status")
            observation = result.get("observation")
            if not isinstance(target, str) or target.casefold() not in expected or target.casefold() in observed:
                raise ValidationError(
                    "invalid_preservation_results",
                    "Preservation targets must exactly match the revision contract.",
                )
            if status not in {"preserved", "changed", "uncertain"}:
                raise ValidationError("invalid_preservation_results", "Preservation status is invalid.")
            if not isinstance(observation, str) or not observation.strip() or len(observation.strip()) > 2000:
                raise ValidationError(
                    "invalid_preservation_results",
                    "Preservation observations must be non-empty and concise.",
                )
            observed[target.casefold()] = status
        if set(observed) != set(expected):
            raise ValidationError(
                "invalid_preservation_results",
                "Preservation targets must exactly match the revision contract.",
            )

        dynamic = {
            f"hard_preserve_violation:{item['target'].casefold()}"
            for item in preserve
            if item.get("strength") == "hard"
        }
        if not isinstance(hard_failures, list) or not all(
            isinstance(failure, str) for failure in hard_failures
        ):
            return dynamic
        required = {
            f"hard_preserve_violation:{expected[key]['target'].casefold()}"
            for key, status in observed.items()
            if expected[key].get("strength") == "hard" and status == "changed"
        }
        reported = {failure for failure in hard_failures if failure in dynamic}
        if reported != required:
            raise ValidationError(
                "inconsistent_preservation_results",
                "Changed hard-preserve targets require exactly their registered hard failures.",
            )
        return dynamic

    def _recover_stale_attempt(
        self,
        run_id: str,
        manifest: dict[str, object],
    ) -> dict[str, object]:
        lock_path = self._lock_path(run_id)
        metadata = self._read_lock_metadata(lock_path)
        if (
            metadata is not None
            and self._lock_metadata_has_live_owner(metadata)
            or metadata is None
            and self._pending_lock_has_live_owner(lock_path.parent)
        ):
            return copy.deepcopy(manifest)

        stale_path: Path | None = None
        try:
            stale_path = self._claim_stale_lock(lock_path, run_id)
            recovery_path, recovery_token = self._acquire_lock(self._run_root(run_id))
            current = self._read_manifest(run_id)
            if not self._lock_is_owned(recovery_path, recovery_token):
                raise ConflictError("run_busy", "Recovery lock ownership changed.", {"run_id": run_id})
            active = current.get("active_attempt")
            if not isinstance(active, dict) or active.get("status") != "running":
                return copy.deepcopy(current)
            interrupted = copy.deepcopy(active)
            interrupted["status"] = "interrupted"
            interrupted["interrupted_at"] = utc_now()
            self._attempts(current).append(interrupted)
            current["active_attempt"] = None
            current["state"] = current.get("last_stable_state", "created")
            warnings = current.get("warnings")
            if not isinstance(warnings, list):
                raise ArtifactError("corrupt_manifest", "Manifest warnings must be an array.")
            if "interrupted_attempt_recovered" not in warnings:
                warnings.append("interrupted_attempt_recovered")
            return self._save_manifest(run_id, current)
        finally:
            if "recovery_path" in locals() and "recovery_token" in locals():
                self._release_lock(recovery_path, recovery_token)
            if stale_path is not None:
                try:
                    stale_path.unlink()
                except FileNotFoundError:
                    pass

    def _claim_stale_lock(
        self,
        lock_path: Path,
        run_id: str,
        *,
        ignored_pending_token: str | None = None,
    ) -> Path | None:
        stale_path = lock_path.with_name(f"{lock_path.name}.stale.{secrets.token_hex(16)}")
        try:
            lock_path.rename(stale_path)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ConflictError("run_busy", "Stale run lock cannot be claimed.", {"run_id": run_id}) from error

        claimed_metadata = self._read_lock_metadata(stale_path)
        claimed_live = (
            claimed_metadata is not None
            and self._lock_metadata_has_live_owner(claimed_metadata)
            or claimed_metadata is None
            and self._pending_lock_has_live_owner(lock_path.parent, ignored_pending_token)
        )
        if claimed_live:
            try:
                stale_path.rename(lock_path)
            except FileExistsError:
                try:
                    stale_path.unlink()
                except FileNotFoundError:
                    pass
            except OSError as error:
                raise ConflictError("run_busy", "Live run lock cannot be restored.", {"run_id": run_id}) from error
            raise ConflictError("run_busy", "Run lock was replaced by a live owner.", {"run_id": run_id})
        return stale_path

    def _read_lock_metadata(self, lock_path: Path) -> dict[str, object] | None:
        try:
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(metadata, dict) or not self._is_valid_lock_metadata(metadata):
            return None
        return metadata

    def _is_valid_lock_metadata(self, metadata: dict[str, object]) -> bool:
        owner_pid = metadata.get("owner_pid")
        owner_token = metadata.get("owner_token")
        owner_identity = metadata.get("owner_process_identity")
        created_at = metadata.get("created_at")
        return (
            isinstance(owner_pid, int)
            and not isinstance(owner_pid, bool)
            and owner_pid > 0
            and isinstance(owner_token, str)
            and bool(owner_token)
            and (owner_identity is None or isinstance(owner_identity, str))
            and isinstance(created_at, str)
            and bool(created_at)
        )

    def _lock_is_owned(self, lock_path: Path, owner_token: str) -> bool:
        metadata = self._read_lock_metadata(lock_path)
        return metadata is not None and metadata.get("owner_token") == owner_token

    def _lock_metadata_has_live_owner(self, metadata: dict[str, object]) -> bool:
        owner_pid = metadata.get("owner_pid")
        if not isinstance(owner_pid, int) or isinstance(owner_pid, bool) or owner_pid <= 0:
            return False
        if not is_process_alive(owner_pid):
            return False
        recorded_identity = metadata.get("owner_process_identity")
        current_identity = process_identity(owner_pid)
        if isinstance(recorded_identity, str) and current_identity is not None:
            return recorded_identity == current_identity
        return True

    def _rounds(self, manifest: dict[str, object]) -> list[dict[str, object]]:
        rounds = manifest.get("rounds")
        if not isinstance(rounds, list) or not all(isinstance(value, dict) for value in rounds):
            raise ArtifactError("corrupt_manifest", "Manifest rounds must be an array of objects.")
        return rounds

    def _attempts(self, manifest: dict[str, object]) -> list[dict[str, object]]:
        attempts = manifest.get("attempts")
        if not isinstance(attempts, list) or not all(isinstance(value, dict) for value in attempts):
            raise ArtifactError("corrupt_manifest", "Manifest attempts must be an array of objects.")
        return attempts

    def _reviews(self, manifest: dict[str, object]) -> list[dict[str, object]]:
        reviews = manifest.get("reviews")
        if not isinstance(reviews, list) or not all(isinstance(value, dict) for value in reviews):
            raise ArtifactError("corrupt_manifest", "Manifest reviews must be an array of objects.")
        return reviews

    def _round_by_number(
        self,
        manifest: dict[str, object],
        round_number: int,
    ) -> dict[str, object] | None:
        for round_value in self._rounds(manifest):
            if round_value.get("round_number") == round_number:
                return round_value
        return None

    def _round_has_review(self, manifest: dict[str, object], round_number: int) -> bool:
        return any(review.get("round_number") == round_number for review in self._reviews(manifest))

    def _review_by_number(
        self,
        manifest: dict[str, object],
        round_number: int,
    ) -> dict[str, object] | None:
        for review in self._reviews(manifest):
            if review.get("round_number") == round_number:
                return review
        return None

    def _quality_status(self, manifest: dict[str, object], review: dict[str, object]) -> str:
        return "accepted" if review_is_eligible(manifest, review) else "needs_user_review"

    @staticmethod
    def _validate_final_summary(summary: object) -> None:
        if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 2000:
            raise ValidationError("invalid_final_summary", "Final summary must be non-empty and concise.")

    @staticmethod
    def _finalize_result_after_commit(
        manifest: dict[str, object],
        commit: Callable[[], object] | None,
    ) -> dict[str, object]:
        result = copy.deepcopy(manifest)
        if commit is None:
            return result
        try:
            commit()
        except Exception:
            warnings = result.get("warnings")
            if not isinstance(warnings, list):
                warnings = []
                result["warnings"] = warnings
            if "finalize_cleanup_failed" not in warnings:
                warnings.append("finalize_cleanup_failed")
            result["finalize_cleanup_warning"] = {
                "code": "finalize_cleanup_failed",
                "message": "Final manifest committed, but rollback-artifact cleanup failed.",
            }
        return result

    def _select_final_round(
        self,
        manifest: dict[str, object],
        round_number: int,
        summary: str,
    ) -> None:
        if not isinstance(round_number, int) or isinstance(round_number, bool) or not 1 <= round_number <= 3:
            raise ValidationError("invalid_round_number", "Round number must be an integer from 1 to 3.")
        if manifest.get("state") == "finalized" or manifest.get("final") is not None:
            raise StateError("already_finalized", "Run already has a final selection.")
        if manifest.get("active_attempt") is not None:
            raise ConflictError("run_busy", "Cannot finalize while a generation attempt is active.")
        self._require_finalizable_state(manifest)
        selected = self._round_by_number(manifest, round_number)
        if selected is None:
            raise StateError("round_not_found", "Selected round does not exist.", {"round_number": round_number})
        review = self._review_by_number(manifest, round_number)
        if review is None:
            raise StateError("round_requires_review", "Selected round must be reviewed before finalization.")
        final: dict[str, object] = {
            "round_number": round_number,
            "summary": summary.strip(),
            "finalized_at": utc_now(),
            "quality_status": self._quality_status(manifest, review),
        }
        image = selected.get("image")
        if isinstance(image, dict):
            final["image"] = copy.deepcopy(image)
            if isinstance(image.get("path"), str):
                final["path"] = image["path"]
        manifest["final"] = final
        manifest["state"] = "finalized"
        manifest["last_stable_state"] = "finalized"

    def _require_finalizable_state(self, manifest: dict[str, object]) -> None:
        if manifest.get("state") != "reviewed" or manifest.get("last_stable_state") != "reviewed":
            raise StateError("round_requires_review", "Latest generated round must be reviewed before finalization.")
        rounds = self._rounds(manifest)
        if not rounds:
            raise StateError("round_requires_review", "At least one generated round must be reviewed.")
        latest_number = rounds[-1].get("round_number")
        if not isinstance(latest_number, int) or not self._round_has_review(manifest, latest_number):
            raise StateError("round_requires_review", "Latest generated round must be reviewed before finalization.")

    def _final_paths(self, run_root: Path, manifest: dict[str, object]) -> set[Path]:
        final = manifest.get("final")
        if isinstance(final, str):
            path_values = {final}
        elif isinstance(final, dict) and isinstance(final.get("path"), str):
            path_values = {final["path"]}
            image = final.get("image")
            if isinstance(image, dict) and isinstance(image.get("path"), str):
                path_values.add(image["path"])
            postprocess = final.get("postprocess")
            if isinstance(postprocess, dict) and postprocess.get("status") == "completed":
                for field in ("source", "output"):
                    metadata = postprocess.get(field)
                    if not isinstance(metadata, dict) or not isinstance(metadata.get("path"), str):
                        raise ArtifactError(
                            "invalid_final_artifact",
                            "Completed postprocess metadata must identify every retained final artifact.",
                        )
                    path_values.add(metadata["path"])
        else:
            raise ArtifactError(
                "invalid_final_artifact",
                "Final metadata must identify a retained artifact path.",
            )

        resolved_paths: set[Path] = set()
        for path_value in path_values:
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
            try:
                final_stat = os.stat(candidate, follow_symlinks=False)
                link_like = _path_is_link_like(candidate)
            except OSError as error:
                raise ArtifactError(
                    "invalid_final_artifact",
                    "Final artifact must be a retained regular file.",
                    {"path": str(candidate)},
                ) from error
            if link_like or not stat.S_ISREG(final_stat.st_mode):
                raise ArtifactError(
                    "invalid_final_artifact",
                    "Final artifact must be a retained regular file.",
                    {"path": str(candidate)},
                )
            resolved_paths.add(resolved)
        return resolved_paths

    def _prune_intermediate_references(self, manifest: dict[str, object], cleaned_at: str) -> None:
        if manifest.get("active_attempt") is not None:
            raise ArtifactError("corrupt_manifest", "Finalized run cannot retain an active attempt.")
        for field in ("attempts", "rounds", "masks"):
            records = manifest.get(field)
            if not isinstance(records, list):
                raise ArtifactError("corrupt_manifest", f"Manifest {field} must be an array.")
            for record in records:
                if not isinstance(record, dict):
                    raise ArtifactError("corrupt_manifest", f"Manifest {field} entries must be objects.")
                removed_reference = False
                for key in ("image", "preview", "path", "overlay"):
                    if key in record:
                        del record[key]
                        removed_reference = True
                backend_result = record.get("backend_result")
                if isinstance(backend_result, dict) and "path" in backend_result:
                    del backend_result["path"]
                    removed_reference = True
                if removed_reference:
                    record["artifacts_cleaned_at"] = cleaned_at

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


def _path_is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    path_stat = os.lstat(path)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)
