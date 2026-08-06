from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlsplit

from .bootstrap_catalog import MAX_ARTIFACT_BYTES, BootstrapArtifact
from .bootstrap_download import download_cache_path, download_verified, safe_extract_portable
from .backend_lifecycle import build_comfyui_start_config
from .client_setup import managed_comfyui_server_command
from .errors import ArtifactError, StateError, ValidationError
from ._filesystem_capability import (
    open_exclusive_output,
    promote_owned_path_no_replace,
    remove_owned_path,
)


_PLAN_ID = re.compile(r"[0-9a-f]{24}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_PLAN_FIELDS = frozenset({"schema_version", "plan_id", "scope_sha256", "confirmation", "scope"})
_TRANSACTION_FIELDS = frozenset({
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
_SCOPE_FIELDS = frozenset({
    "schema_version",
    "manifest_sha256",
    "install_root",
    "status",
    "reason",
    "facts",
    "actions",
    "required_download_bytes",
    "required_disk_bytes",
    "artifacts",
    "workflow",
})
_ARTIFACT_FIELDS = frozenset({
    "kind",
    "artifact_id",
    "version",
    "source_url",
    "source_host",
    "byte_size",
    "sha256",
    "license_id",
    "license_url",
    "install_relative_path",
    "archive_format",
    "minimum_vram_gb",
})
_FACT_FIELDS = frozenset({
    "platform",
    "architecture",
    "gpu_vendor",
    "gpu_generation",
    "vram_bytes",
    "windows_build",
    "free_disk_bytes",
    "network_allowed",
    "endpoint_ready",
    "portable_status",
    "model_status",
})
_SUPPORTED_GPU_GENERATIONS = frozenset({
    "rtx-20-series",
    "rtx-30-series",
    "rtx-40-series",
    "rtx-50-series",
})
_KNOWN_EXECUTION_FAILURE_CODES = frozenset({
    "archive_extract_failed",
    "archive_postcheck_failed",
    "cached_artifact_mismatch",
    "download_failed",
    "download_hash_mismatch",
    "download_interrupted",
    "download_length_mismatch",
    "download_oversize",
    "download_range_mismatch",
    "download_redirect_not_allowed",
    "download_status_rejected",
    "downloaded_artifact_invalid",
    "extractor_dependency_mismatch",
    "extractor_dependency_unavailable",
    "insecure_download_source",
    "invalid_archive_path",
    "invalid_download_artifact",
    "invalid_download_options",
    "invalid_download_part",
    "invalid_extraction_options",
    "invalid_install_root",
    "invalid_portable_layout",
    "model_destination_conflict",
    "portable_destination_conflict",
    "portable_runtime_smoke_failed",
    "portable_staging_conflict",
    "unsafe_archive",
    "unsafe_model_destination",
})
_PERSISTED_EXECUTION_FAILURE_CODES = _KNOWN_EXECUTION_FAILURE_CODES | {
    "bootstrap_execution_failed"
}
_MAX_STATE_BYTES = 512 * 1024
_PORTABLE_RUNTIME_SMOKE_TIMEOUT_SECONDS = 15.0


class _DuplicateStateKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _VerifiedArtifactFile:
    path: Path
    identity: os.stat_result


@dataclass(frozen=True, slots=True)
class _OwnedDirectory:
    path: Path
    identity: os.stat_result


def apply_bootstrap_plan(
    plan_id: str,
    confirmation: str,
    *,
    state_dir: Path,
    downloader: Callable[[BootstrapArtifact, Path], Path] = download_verified,
) -> dict[str, object]:
    """Execute one exact persisted bootstrap plan at most once."""
    if not isinstance(plan_id, str) or _PLAN_ID.fullmatch(plan_id) is None:
        raise ValidationError(
            "invalid_bootstrap_plan_id",
            "Bootstrap plan ID must be 24 lowercase hexadecimal characters.",
        )
    if not isinstance(confirmation, str) or not confirmation:
        raise ValidationError(
            "bootstrap_confirmation_required",
            "Bootstrap execution requires the exact displayed confirmation.",
        )

    requested_root = Path(state_dir).expanduser()
    try:
        root_stat = requested_root.lstat()
    except OSError as error:
        raise StateError(
            "invalid_bootstrap_state_dir",
            "Bootstrap state directory must be an existing safe directory.",
        ) from error
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not requested_root.is_absolute()
        or stat.S_ISLNK(root_stat.st_mode)
        or not stat.S_ISDIR(root_stat.st_mode)
        or bool(getattr(root_stat, "st_file_attributes", 0) & reparse_flag)
    ):
        raise StateError(
            "invalid_bootstrap_state_dir",
            "Bootstrap state directory must be absolute and must not be link-like.",
        )
    root = requested_root.resolve()
    plan_path = root / f"{plan_id}.json"
    if not plan_path.exists():
        raise StateError(
            "bootstrap_plan_not_found",
            "Bootstrap plan record does not exist.",
            {"path": str(plan_path)},
        )
    plan = _read_json(plan_path, "invalid_bootstrap_plan")
    if set(plan) != _PLAN_FIELDS:
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan record has missing or unknown fields.",
        )
    scope = plan.get("scope")
    if not isinstance(scope, dict):
        raise ValidationError(
            "invalid_bootstrap_plan",
            "Bootstrap plan scope must be a JSON object.",
        )
    if set(scope) != _SCOPE_FIELDS or scope.get("schema_version") != 1:
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan scope has missing, unknown, or unsupported fields.",
        )
    canonical_scope = json.dumps(
        scope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    scope_sha256 = hashlib.sha256(canonical_scope).hexdigest()
    expected_confirmation = f"bootstrap:{plan_id}:{scope_sha256}"
    if (
        plan.get("schema_version") != 1
        or plan.get("plan_id") != plan_id
        or plan.get("scope_sha256") != scope_sha256
        or plan_id != scope_sha256[:24]
        or plan.get("confirmation") != expected_confirmation
    ):
        raise ValidationError(
            "bootstrap_plan_identity_mismatch",
            "Bootstrap plan identity does not match its canonical scope.",
        )
    if confirmation != expected_confirmation:
        raise ValidationError(
            "bootstrap_confirmation_mismatch",
            "Bootstrap confirmation does not match the exact frozen plan.",
        )
    if scope.get("status") != "confirmation_required":
        raise StateError(
            "bootstrap_plan_not_executable",
            "Only a confirmation-required bootstrap plan can be applied.",
        )
    _validate_install_root_identity(scope.get("install_root"), root)
    _validate_action_contract(scope)
    normalized_artifacts = _normalize_artifacts(scope)
    _validate_scope_byte_contract(scope, normalized_artifacts)
    install_root = Path(scope["install_root"])
    portable_root = install_root / normalized_artifacts["comfyui"].install_relative_path
    model_path = install_root.joinpath(
        *PurePosixPath(normalized_artifacts["model"].install_relative_path).parts
    )
    portable_pre_existing = os.path.lexists(portable_root)
    model_pre_existing = os.path.lexists(model_path)
    expected_downloaded_artifacts = tuple(
        normalized_artifacts[action["kind"].removeprefix("download_")].artifact_id
        for action in scope["actions"]
        if action["kind"] in {"download_comfyui", "download_model"}
    )
    expected_completed_retained_state = {
        "portable": (
            "installed"
            if scope["facts"]["portable_status"] == "missing"
            else "verified_pre_existing"
        ),
        "model": (
            "installed" if scope["facts"]["model_status"] == "missing" else "verified_pre_existing"
        ),
        "verified_cache_artifacts": list(expected_downloaded_artifacts),
    }

    transaction_path = root / f"{plan_id}.transaction.json"
    existing_result = _existing_transaction_result(
        transaction_path,
        plan_id,
        scope_sha256,
        confirmation,
        expected_downloaded_artifacts,
        expected_completed_retained_state,
        portable_root,
        model_path,
        normalized_artifacts,
    )
    if existing_result is not None:
        return existing_result

    claim_path = root / f".{plan_id}.apply.lock"
    try:
        claim_path.mkdir()
    except FileExistsError as error:
        existing_result = _existing_transaction_result(
            transaction_path,
            plan_id,
            scope_sha256,
            confirmation,
            expected_downloaded_artifacts,
            expected_completed_retained_state,
            portable_root,
            model_path,
            normalized_artifacts,
        )
        if existing_result is not None:
            return existing_result
        raise StateError(
            "bootstrap_transaction_in_progress",
            "Another execution already owns this bootstrap confirmation.",
        ) from error
    except OSError as error:
        raise StateError(
            "bootstrap_transaction_claim_failed",
            "Bootstrap transaction ownership could not be acquired safely.",
        ) from error

    try:
        existing_result = _existing_transaction_result(
            transaction_path,
            plan_id,
            scope_sha256,
            confirmation,
            expected_downloaded_artifacts,
            expected_completed_retained_state,
            portable_root,
            model_path,
            normalized_artifacts,
        )
        if existing_result is not None:
            return existing_result
        initial_retained_state = {
            "portable": "pre_existing" if portable_pre_existing else "missing",
            "model": "pre_existing" if model_pre_existing else "missing",
            "verified_cache_artifacts": [],
        }
        transaction = {
            "schema_version": 1,
            "plan_id": plan_id,
            "scope_sha256": scope_sha256,
            "confirmation_sha256": _sha256_text(confirmation),
            "status": "in_progress",
            "downloaded_artifacts": [],
            "failure_code": None,
            "retained_state": initial_retained_state,
            "recoverable_next_actions": _recoverable_next_actions(initial_retained_state),
        }
        _atomic_write_state(transaction_path, transaction, root, root_stat)

        downloaded: list[str] = []
        downloaded_paths: dict[str, _VerifiedArtifactFile] = {}
        managed_command: tuple[str, ...] | None = None
        portable_promoted = False
        model_promoted = False
        portable_reuse_verified = False
        model_reuse_verified = False
        actions = scope["actions"]
        try:
            for action in actions:
                kind = action["kind"]
                if kind in {"download_comfyui", "download_model"}:
                    artifact_kind = kind.removeprefix("download_")
                    artifact = normalized_artifacts[artifact_kind]
                    downloaded_path = downloader(artifact, root.parent / "cache")
                    downloaded_paths[artifact_kind] = _require_exact_artifact_file(
                        downloaded_path,
                        artifact,
                    )
                    downloaded.append(artifact.artifact_id)
                    _record_in_progress_boundary(
                        transaction,
                        transaction_path,
                        root,
                        root_stat,
                        _retained_install_state(
                            portable_root,
                            model_path,
                            downloaded,
                            portable_pre_existing=portable_pre_existing,
                            model_pre_existing=model_pre_existing,
                            portable_promoted=portable_promoted,
                            model_promoted=model_promoted,
                            portable_reuse_verified=portable_reuse_verified,
                            model_reuse_verified=model_reuse_verified,
                            model_artifact=normalized_artifacts["model"],
                        ),
                        downloaded,
                    )
                elif kind == "extract_comfyui":
                    portable_root = safe_extract_portable(
                        downloaded_paths["comfyui"].path,
                        install_root,
                        expected_root=normalized_artifacts["comfyui"].install_relative_path,
                        plan_id=plan_id,
                        expected_byte_size=normalized_artifacts["comfyui"].byte_size,
                        expected_sha256=normalized_artifacts["comfyui"].sha256,
                    )
                    build_comfyui_start_config(portable_root)
                    _verify_portable_runtime(portable_root)
                    portable_promoted = True
                    _record_in_progress_boundary(
                        transaction,
                        transaction_path,
                        root,
                        root_stat,
                        _retained_install_state(
                            portable_root,
                            model_path,
                            downloaded,
                            portable_pre_existing=portable_pre_existing,
                            model_pre_existing=model_pre_existing,
                            portable_promoted=portable_promoted,
                            model_promoted=model_promoted,
                            portable_reuse_verified=portable_reuse_verified,
                            model_reuse_verified=model_reuse_verified,
                            model_artifact=normalized_artifacts["model"],
                        ),
                        downloaded,
                    )
                elif kind == "install_model":
                    model_path = _place_model_no_overwrite(
                        downloaded_paths["model"],
                        model_path,
                        portable_root,
                        normalized_artifacts["model"],
                        plan_id=plan_id,
                    )
                    model_promoted = True
                    _record_in_progress_boundary(
                        transaction,
                        transaction_path,
                        root,
                        root_stat,
                        _retained_install_state(
                            portable_root,
                            model_path,
                            downloaded,
                            portable_pre_existing=portable_pre_existing,
                            model_pre_existing=model_pre_existing,
                            portable_promoted=portable_promoted,
                            model_promoted=model_promoted,
                            portable_reuse_verified=portable_reuse_verified,
                            model_reuse_verified=model_reuse_verified,
                            model_artifact=normalized_artifacts["model"],
                        ),
                        downloaded,
                    )
                elif kind == "reuse_portable":
                    build_comfyui_start_config(portable_root)
                    _verify_portable_runtime(portable_root)
                    portable_reuse_verified = True
                elif kind == "reuse_model":
                    _require_exact_artifact_file(model_path, normalized_artifacts["model"])
                    model_reuse_verified = True
                elif kind == "verify_install":
                    _require_exact_artifact_file(model_path, normalized_artifacts["model"])
                    managed_command = managed_comfyui_server_command(portable_root)
        except Exception as error:
            retained_state = _retained_install_state(
                portable_root,
                model_path,
                downloaded,
                portable_pre_existing=portable_pre_existing,
                model_pre_existing=model_pre_existing,
                portable_promoted=portable_promoted,
                model_promoted=model_promoted,
                portable_reuse_verified=portable_reuse_verified,
                model_reuse_verified=model_reuse_verified,
                model_artifact=normalized_artifacts["model"],
            )
            recoverable_next_actions = _recoverable_next_actions(retained_state)
            failure_code = _execution_failure_code(error)
            transaction["status"] = "failed"
            transaction["downloaded_artifacts"] = downloaded
            transaction["failure_code"] = failure_code
            transaction["retained_state"] = retained_state
            transaction["recoverable_next_actions"] = recoverable_next_actions
            _atomic_write_state(transaction_path, transaction, root, root_stat)
            failed = _result("recoverable_failure", plan_id, scope_sha256)
            failed.update(
                ok=False,
                error={"code": transaction["failure_code"]},
                retained_state=retained_state,
                recoverable_next_actions=recoverable_next_actions,
            )
            return failed

        transaction["status"] = "completed"
        transaction["downloaded_artifacts"] = downloaded
        transaction["failure_code"] = None
        transaction["retained_state"] = _retained_install_state(
            portable_root,
            model_path,
            downloaded,
            portable_pre_existing=portable_pre_existing,
            model_pre_existing=model_pre_existing,
            portable_promoted=portable_promoted,
            model_promoted=model_promoted,
            portable_reuse_verified=portable_reuse_verified,
            model_reuse_verified=model_reuse_verified,
            model_artifact=normalized_artifacts["model"],
        )
        transaction["recoverable_next_actions"] = []
        _atomic_write_state(transaction_path, transaction, root, root_stat)
        return _installed_result(
            "installed",
            plan_id,
            scope_sha256,
            portable_root,
            model_path,
            normalized_artifacts["model"],
            managed_command=managed_command,
        )
    finally:
        try:
            claim_path.rmdir()
        except OSError:
            pass


def _execution_failure_code(error: Exception) -> str:
    if (
        isinstance(error, ArtifactError)
        and isinstance(error.code, str)
        and error.code in _KNOWN_EXECUTION_FAILURE_CODES
    ):
        return error.code
    return "bootstrap_execution_failed"


def _verify_portable_runtime(portable_root: Path) -> None:
    python = portable_root / "python_embeded" / "python.exe"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(python), "-I", "-c", "import PIL"],
            cwd=str(portable_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_PORTABLE_RUNTIME_SMOKE_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ArtifactError(
            "portable_runtime_smoke_failed",
            "Portable embedded Python could not complete the bounded Pillow import smoke.",
        ) from error
    if completed.returncode != 0:
        raise ArtifactError(
            "portable_runtime_smoke_failed",
            "Portable embedded Python could not import Pillow.",
            {"returncode": completed.returncode},
        )


def _existing_transaction_result(
    transaction_path: Path,
    plan_id: str,
    scope_sha256: str,
    confirmation: str,
    expected_downloaded_artifacts: tuple[str, ...],
    expected_completed_retained_state: dict[str, object],
    portable_root: Path,
    model_path: Path,
    artifacts: dict[str, BootstrapArtifact],
) -> dict[str, object] | None:
    model_artifact = artifacts["model"]
    if not os.path.lexists(transaction_path):
        return None
    transaction = _read_json(transaction_path, "invalid_bootstrap_transaction")
    _validate_transaction(
        transaction,
        plan_id,
        scope_sha256,
        confirmation,
        expected_downloaded_artifacts,
        expected_completed_retained_state,
    )
    if transaction["status"] == "completed":
        return _installed_result(
            "already_installed",
            plan_id,
            scope_sha256,
            portable_root,
            model_path,
            model_artifact,
        )
    reconciled_retained_state = _reconcile_retained_state(
        transaction,
        portable_root,
        model_path,
        artifacts,
        transaction_path.parent.parent / "cache",
    )
    stored_retained_state = transaction["retained_state"]
    for component in ("portable", "model"):
        if (
            stored_retained_state[component]
            in {"installed", "verified_pre_existing"}
            and stored_retained_state[component] != reconciled_retained_state[component]
        ):
            raise StateError(
                "invalid_bootstrap_transaction",
                "Bootstrap transaction retained state does not match current evidence.",
            )
    reconciled_next_actions = _recoverable_next_actions(reconciled_retained_state)
    raise StateError(
        "bootstrap_confirmation_consumed",
        "Bootstrap confirmation has already been consumed by another transaction state.",
        {
            "transaction_status": transaction["status"],
            "retained_state": reconciled_retained_state,
            "recoverable_next_actions": reconciled_next_actions,
        },
    )


def _atomic_write_state(
    path: Path,
    value: dict[str, object],
    state_root: Path,
    expected_root_stat: os.stat_result,
) -> None:
    _require_same_state_root(state_root, expected_root_stat)
    serialized = (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(serialized) > _MAX_STATE_BYTES:
        raise StateError(
            "invalid_bootstrap_transaction",
            "Bootstrap transaction exceeds the state byte limit.",
        )
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    opened_stat: os.stat_result | None = None
    try:
        descriptor = os.open(temp_path, flags, 0o600)
        opened_stat = os.fstat(descriptor)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        current_stat = temp_path.lstat()
        if opened_stat is None or not os.path.samestat(opened_stat, current_stat):
            raise OSError("bootstrap transaction temporary identity drifted")
        _require_same_state_root(state_root, expected_root_stat)
        os.replace(temp_path, path)
    except (OSError, TypeError, ValueError) as error:
        raise StateError(
            "bootstrap_transaction_write_failed",
            "Bootstrap transaction state could not be written atomically.",
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            if os.path.lexists(temp_path):
                temp_stat = temp_path.lstat()
                if opened_stat is not None and os.path.samestat(opened_stat, temp_stat):
                    temp_path.unlink()
        except OSError:
            pass


def _record_in_progress_boundary(
    transaction: dict[str, object],
    transaction_path: Path,
    state_root: Path,
    expected_root_stat: os.stat_result,
    retained_state: dict[str, object],
    downloaded_artifacts: list[str],
) -> None:
    transaction["status"] = "in_progress"
    transaction["downloaded_artifacts"] = list(downloaded_artifacts)
    transaction["failure_code"] = None
    transaction["retained_state"] = retained_state
    transaction["recoverable_next_actions"] = _recoverable_next_actions(retained_state)
    _atomic_write_state(transaction_path, transaction, state_root, expected_root_stat)


def _require_exact_artifact_file(
    value: object,
    artifact: BootstrapArtifact,
) -> _VerifiedArtifactFile:
    try:
        path = Path(value)
        path_stat = path.lstat()
    except (OSError, TypeError, ValueError) as error:
        raise ArtifactError(
            "downloaded_artifact_invalid",
            "Downloader output must be one exact verified artifact file.",
        ) from error
    if (
        not path.is_absolute()
        or not _safe_artifact_file_stat(path_stat, artifact.byte_size)
    ):
        raise ArtifactError(
            "downloaded_artifact_invalid",
            "Downloader output must be one exact verified artifact file.",
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            opened_stat = os.fstat(stream.fileno())
            if (
                not _safe_artifact_file_stat(opened_stat, artifact.byte_size)
                or not os.path.samestat(path_stat, opened_stat)
            ):
                raise OSError("artifact identity changed while opening")
            remaining = artifact.byte_size
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    raise OSError("artifact ended before its frozen byte size")
                digest.update(block)
                remaining -= len(block)
            if stream.read(1):
                raise OSError("artifact exceeds its frozen byte size")
        if not os.path.samestat(path_stat, path.lstat()):
            raise OSError("artifact identity changed while reading")
    except OSError as error:
        raise ArtifactError(
            "downloaded_artifact_invalid",
            "Downloader output could not be verified safely.",
        ) from error
    if digest.hexdigest() != artifact.sha256:
        raise ArtifactError(
            "downloaded_artifact_invalid",
            "Downloader output size or digest does not match the frozen artifact.",
        )
    return _VerifiedArtifactFile(path=path, identity=opened_stat)


def _place_model_no_overwrite(
    source: _VerifiedArtifactFile,
    destination: Path,
    portable_root: Path,
    artifact: BootstrapArtifact,
    *,
    plan_id: str,
) -> Path:
    if os.path.lexists(destination):
        raise ArtifactError(
            "model_destination_conflict",
            "Model destination already exists and will not be overwritten.",
            {"path": str(destination)},
        )
    created_directories = _prepare_safe_model_parent(destination, portable_root)
    parent_guard = _capture_model_parent_guard(destination.parent, portable_root)
    staging = destination.with_name(f".{destination.name}.{plan_id}.staging")
    staging_identity: os.stat_result | None = None
    try:
        _require_model_parent_guard(parent_guard)
        with source.path.open("rb") as input_stream:
            source_stat = os.fstat(input_stream.fileno())
            if (
                not _safe_artifact_file_stat(source_stat, artifact.byte_size)
                or not os.path.samestat(source.identity, source_stat)
                or not os.path.samestat(source.identity, source.path.lstat())
            ):
                raise ArtifactError(
                    "downloaded_artifact_invalid",
                    "Verified model source identity changed before placement.",
                )
            try:
                output_stream, staging_identity = open_exclusive_output(
                    staging,
                    parent_guard[0][1],
                )
            except OSError as error:
                raise ArtifactError(
                    "unsafe_model_destination",
                    "Model staging escaped its fixed invocation-owned parent.",
                ) from error
            try:
                _require_model_parent_guard(parent_guard)
                digest = hashlib.sha256()
                remaining = artifact.byte_size
                while remaining:
                    block = input_stream.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ArtifactError(
                            "downloaded_artifact_invalid",
                            "Verified model source ended before its frozen byte size.",
                        )
                    output_stream.write(block)
                    digest.update(block)
                    remaining -= len(block)
                if input_stream.read(1) or digest.hexdigest() != artifact.sha256:
                    raise ArtifactError(
                        "downloaded_artifact_invalid",
                        "Verified model source changed during placement.",
                    )
                output_stream.flush()
                os.fsync(output_stream.fileno())
            finally:
                output_stream.close()
        _require_exact_artifact_file(staging, artifact)
        _require_model_parent_guard(parent_guard)
        promote_owned_path_no_replace(
            staging,
            staging_identity,
            destination,
            parent_guard[0][1],
            directory=False,
        )
        try:
            _require_model_parent_guard(parent_guard)
            if not os.path.samestat(staging_identity, destination.lstat()):
                raise ArtifactError(
                    "unsafe_model_destination",
                    "Model destination identity changed during atomic placement.",
                )
        except BaseException:
            _unlink_owned_file(destination, staging_identity)
            raise
        return _require_exact_artifact_file(destination, artifact).path
    except BaseException:
        _unlink_owned_file(staging, staging_identity)
        for directory in reversed(created_directories):
            if not _remove_owned_empty_directory(directory):
                break
        raise


def _unlink_owned_file(path: Path, identity: os.stat_result | None) -> None:
    if identity is None:
        return
    remove_owned_path(path, identity, directory=False)


def _prepare_safe_model_parent(
    destination: Path,
    portable_root: Path,
) -> list[_OwnedDirectory]:
    try:
        destination.relative_to(portable_root)
    except ValueError as error:
        raise ArtifactError(
            "unsafe_model_destination",
            "Model destination is outside the fixed portable root.",
        ) from error
    lineage: list[Path] = []
    current = destination.parent
    while True:
        lineage.append(current)
        if current == portable_root:
            break
        parent = current.parent
        if parent == current:
            raise ArtifactError(
                "unsafe_model_destination",
                "Model destination does not descend from the fixed portable root.",
            )
        current = parent

    created: list[_OwnedDirectory] = []
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        for directory in reversed(lineage):
            created_here = False
            if not os.path.lexists(directory):
                directory.mkdir()
                created_here = True
            directory_stat = directory.lstat()
            if (
                not stat.S_ISDIR(directory_stat.st_mode)
                or stat.S_ISLNK(directory_stat.st_mode)
                or bool(getattr(directory_stat, "st_file_attributes", 0) & reparse_flag)
            ):
                raise OSError("model destination parent is link-like or not a directory")
            if created_here:
                created.append(_OwnedDirectory(directory, directory_stat))
    except OSError as error:
        for directory in reversed(created):
            if not _remove_owned_empty_directory(directory):
                break
        raise ArtifactError(
            "unsafe_model_destination",
            "Model destination parents must be fixed non-reparse directories.",
        ) from error
    return created


def _remove_owned_empty_directory(owned: _OwnedDirectory) -> bool:
    return remove_owned_path(owned.path, owned.identity, directory=True)


def _capture_model_parent_guard(
    parent: Path,
    portable_root: Path,
) -> tuple[tuple[Path, os.stat_result], ...]:
    identities: list[tuple[Path, os.stat_result]] = []
    current = parent
    try:
        while True:
            current_stat = current.lstat()
            if not _safe_model_directory_stat(current_stat):
                raise OSError("model parent is link-like")
            identities.append((current, current_stat))
            if current == portable_root:
                break
            current = current.parent
    except OSError as error:
        raise ArtifactError(
            "unsafe_model_destination",
            "Model destination parent identity cannot be frozen safely.",
        ) from error
    return tuple(identities)


def _require_model_parent_guard(
    expected: tuple[tuple[Path, os.stat_result], ...],
) -> None:
    try:
        for path, expected_stat in expected:
            current_stat = path.lstat()
            if not _safe_model_directory_stat(current_stat) or not os.path.samestat(
                expected_stat,
                current_stat,
            ):
                raise OSError("model parent identity changed")
    except OSError as error:
        raise ArtifactError(
            "unsafe_model_destination",
            "Model destination parent identity changed at a write boundary.",
        ) from error


def _safe_model_directory_stat(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return (
        stat.S_ISDIR(path_stat.st_mode)
        and not stat.S_ISLNK(path_stat.st_mode)
        and not bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)
    )


def _safe_artifact_file_stat(path_stat: os.stat_result, expected_size: int) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return (
        stat.S_ISREG(path_stat.st_mode)
        and not stat.S_ISLNK(path_stat.st_mode)
        and not bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)
        and path_stat.st_nlink == 1
        and path_stat.st_size == expected_size
    )


def _retained_install_state(
    portable_root: Path,
    model_path: Path,
    downloaded_artifacts: list[str],
    *,
    portable_pre_existing: bool,
    model_pre_existing: bool,
    portable_promoted: bool,
    model_promoted: bool,
    portable_reuse_verified: bool,
    model_reuse_verified: bool,
    model_artifact: BootstrapArtifact,
) -> dict[str, object]:
    portable = "pre_existing" if portable_pre_existing else "missing"
    model = "pre_existing" if model_pre_existing else "missing"
    try:
        if portable_promoted:
            build_comfyui_start_config(portable_root)
            portable = "installed"
        elif portable_reuse_verified:
            build_comfyui_start_config(portable_root)
            portable = "verified_pre_existing"
        elif not portable_pre_existing and os.path.lexists(portable_root):
            portable = "unsafe_drift"
    except (OSError, RuntimeError):
        portable = "unsafe_drift"
    try:
        if model_promoted:
            _require_exact_artifact_file(model_path, model_artifact)
            model = "installed"
        elif model_reuse_verified:
            _require_exact_artifact_file(model_path, model_artifact)
            model = "verified_pre_existing"
        elif not model_pre_existing and os.path.lexists(model_path):
            model = "unsafe_drift"
    except (OSError, ArtifactError):
        model = "unsafe_drift"
    return {
        "portable": portable,
        "model": model,
        "verified_cache_artifacts": list(downloaded_artifacts),
    }


def _recoverable_next_actions(retained_state: dict[str, object]) -> list[str]:
    reusable = {"installed", "verified_pre_existing"}
    if (
        retained_state.get("portable") in reusable
        and retained_state.get("model") in reusable
    ):
        return ["create_new_plan_reusing_retained_install"]
    if retained_state.get("portable") in reusable:
        return ["create_new_plan_reusing_portable"]
    return ["create_new_bootstrap_plan"]


def _installed_result(
    status: str,
    plan_id: str,
    scope_sha256: str,
    portable_root: Path,
    model_path: Path,
    model_artifact: BootstrapArtifact,
    *,
    managed_command: tuple[str, ...] | None = None,
) -> dict[str, object]:
    _require_exact_artifact_file(model_path, model_artifact)
    if managed_command is None:
        managed_command = managed_comfyui_server_command(portable_root)
    result = _result(status, plan_id, scope_sha256)
    result.update(
        portable_root=str(portable_root.resolve()),
        model_path=str(model_path.resolve()),
        rediscovery={
            "status": "deferred",
            "mode": "api_only",
            "next_action": "start_managed_comfyui_then_rediscover",
        },
        setup={
            "status": "ready",
            "managed_comfyui_server_command": list(managed_command),
        },
    )
    return result


def _require_same_state_root(path: Path, expected: os.stat_result) -> None:
    try:
        current = path.lstat()
    except OSError as error:
        raise StateError(
            "invalid_bootstrap_state_dir",
            "Bootstrap state directory identity changed during execution.",
        ) from error
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not stat.S_ISDIR(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or bool(getattr(current, "st_file_attributes", 0) & reparse_flag)
        or not os.path.samestat(expected, current)
    ):
        raise StateError(
            "invalid_bootstrap_state_dir",
            "Bootstrap state directory identity changed during execution.",
        )


def _read_json(path: Path, error_code: str) -> dict[str, object]:
    try:
        path_stat = path.lstat()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)
            or path_stat.st_nlink != 1
            or path_stat.st_size > _MAX_STATE_BYTES
        ):
            raise OSError("state record is not one bounded regular file")
        with path.open("rb") as stream:
            opened_stat = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_nlink != 1
                or opened_stat.st_size > _MAX_STATE_BYTES
                or not os.path.samestat(path_stat, opened_stat)
            ):
                raise OSError("state record identity changed while opening")
            raw = stream.read(_MAX_STATE_BYTES + 1)
        if len(raw) > _MAX_STATE_BYTES:
            raise OSError("state record exceeds byte limit")
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _DuplicateStateKey) as error:
        raise StateError(
            error_code,
            "Bootstrap state record is missing or invalid.",
            {"path": str(path)},
        ) from error
    if not isinstance(value, dict):
        raise StateError(
            error_code,
            "Bootstrap state record must be a JSON object.",
            {"path": str(path)},
        )
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateStateKey(key)
        value[key] = item
    return value


def _validate_install_root_identity(value: object, state_root: Path) -> None:
    if not isinstance(value, str) or not value:
        raise StateError(
            "bootstrap_plan_path_drift",
            "Bootstrap plan install root is missing or invalid.",
        )
    install_root = Path(value).expanduser()
    try:
        resolved = install_root.resolve()
    except (OSError, RuntimeError) as error:
        raise StateError(
            "bootstrap_plan_path_drift",
            "Bootstrap plan install root identity cannot be verified.",
        ) from error
    anchor = Path(install_root.anchor)
    if (
        not install_root.is_absolute()
        or install_root == anchor
        or str(install_root) != value
        or resolved != install_root
        or install_root == state_root
        or install_root in state_root.parents
        or state_root in install_root.parents
    ):
        raise StateError(
            "bootstrap_plan_path_drift",
            "Bootstrap plan install root no longer has its frozen path identity.",
        )
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    current = install_root
    while current != Path(current.anchor):
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            current = current.parent
            continue
        except OSError as error:
            raise StateError(
                "bootstrap_plan_path_drift",
                "Bootstrap plan install root identity cannot be verified.",
            ) from error
        if stat.S_ISLNK(current_stat.st_mode) or bool(
            getattr(current_stat, "st_file_attributes", 0) & reparse_flag
        ):
            raise StateError(
                "bootstrap_plan_path_drift",
                "Bootstrap plan install root traverses a link-like path.",
            )
        current = current.parent


def _validate_transaction(
    transaction: dict[str, object],
    plan_id: str,
    scope_sha256: str,
    confirmation: str,
    expected_downloaded_artifacts: tuple[str, ...],
    expected_completed_retained_state: dict[str, object],
) -> None:
    downloaded = transaction.get("downloaded_artifacts")
    retained_state = transaction.get("retained_state")
    recoverable_next_actions = transaction.get("recoverable_next_actions")
    status_value = transaction.get("status")
    retained_valid = (
        isinstance(retained_state, dict)
        and set(retained_state) == {"portable", "model", "verified_cache_artifacts"}
        and retained_state.get("portable")
        in {"missing", "pre_existing", "verified_pre_existing", "installed", "unsafe_drift"}
        and retained_state.get("model")
        in {"missing", "pre_existing", "verified_pre_existing", "installed", "unsafe_drift"}
        and retained_state.get("verified_cache_artifacts") == downloaded
        and _retained_transition_is_valid(
            retained_state,
            downloaded,
            expected_downloaded_artifacts,
            expected_completed_retained_state,
        )
    )
    if (
        set(transaction) != _TRANSACTION_FIELDS
        or transaction.get("schema_version") != 1
        or transaction.get("plan_id") != plan_id
        or transaction.get("scope_sha256") != scope_sha256
        or transaction.get("confirmation_sha256") != _sha256_text(confirmation)
        or status_value not in {"in_progress", "failed", "completed"}
        or not isinstance(downloaded, list)
        or any(not isinstance(item, str) or not item for item in downloaded)
        or len(downloaded) != len(set(downloaded))
        or (
            status_value == "completed"
            and tuple(downloaded) != expected_downloaded_artifacts
        )
        or (
            status_value in {"in_progress", "failed"}
            and tuple(downloaded) != expected_downloaded_artifacts[:len(downloaded)]
        )
        or not retained_valid
        or not isinstance(recoverable_next_actions, list)
        or any(not isinstance(item, str) or not item for item in recoverable_next_actions)
        or (
            status_value == "completed"
            and (
                transaction.get("failure_code") is not None
                or retained_state != expected_completed_retained_state
                or recoverable_next_actions != []
            )
        )
        or (
            status_value == "in_progress"
            and (
                transaction.get("failure_code") is not None
                or recoverable_next_actions != _recoverable_next_actions(retained_state)
            )
        )
        or (
            status_value == "failed"
            and (
                transaction.get("failure_code") not in _PERSISTED_EXECUTION_FAILURE_CODES
                or recoverable_next_actions != _recoverable_next_actions(retained_state)
            )
        )
    ):
        raise StateError(
            "invalid_bootstrap_transaction",
            "Bootstrap transaction record does not match the exact frozen plan.",
        )


def _retained_transition_is_valid(
    retained_state: dict[str, object],
    downloaded: object,
    expected_downloaded_artifacts: tuple[str, ...],
    expected_completed_retained_state: dict[str, object],
) -> bool:
    if not isinstance(downloaded, list):
        return False
    required_downloads = _component_download_ids(
        expected_downloaded_artifacts,
        expected_completed_retained_state,
    )
    for component in ("portable", "model"):
        state = retained_state.get(component)
        completed_state = expected_completed_retained_state.get(component)
        if completed_state == "installed":
            if state not in {"missing", "pre_existing", "installed", "unsafe_drift"}:
                return False
            required_download = required_downloads[component]
            if state == "installed" and required_download not in downloaded:
                return False
        elif completed_state == "verified_pre_existing":
            if state not in {
                "missing",
                "pre_existing",
                "verified_pre_existing",
                "unsafe_drift",
            }:
                return False
        else:
            return False
    return True


def _component_download_ids(
    expected_downloaded_artifacts: tuple[str, ...],
    expected_completed_retained_state: dict[str, object],
) -> dict[str, str | None]:
    result: dict[str, str | None] = {"portable": None, "model": None}
    index = 0
    for component in ("portable", "model"):
        if expected_completed_retained_state.get(component) == "installed":
            if index >= len(expected_downloaded_artifacts):
                return {"portable": None, "model": None}
            result[component] = expected_downloaded_artifacts[index]
            index += 1
    return result


def _reconcile_retained_state(
    transaction: dict[str, object],
    portable_root: Path,
    model_path: Path,
    artifacts: dict[str, BootstrapArtifact],
    cache_dir: Path,
) -> dict[str, object]:
    model_artifact = artifacts["model"]
    downloaded = list(transaction["downloaded_artifacts"])
    stored_retained_state = transaction["retained_state"]
    stored_portable = stored_retained_state["portable"]
    if stored_portable == "missing":
        portable_state = "unsafe_drift" if os.path.lexists(portable_root) else "missing"
    elif stored_portable == "pre_existing":
        portable_state = "pre_existing" if os.path.lexists(portable_root) else "unsafe_drift"
    elif stored_portable == "unsafe_drift":
        portable_state = "unsafe_drift"
    else:
        try:
            build_comfyui_start_config(portable_root)
        except Exception:
            portable_state = "unsafe_drift"
        else:
            portable_state = stored_portable

    stored_model = stored_retained_state["model"]
    if stored_model == "missing":
        model_state = "unsafe_drift" if os.path.lexists(model_path) else "missing"
    elif stored_model == "pre_existing":
        model_state = "pre_existing" if os.path.lexists(model_path) else "unsafe_drift"
    elif stored_model == "unsafe_drift":
        model_state = "unsafe_drift"
    else:
        try:
            _require_exact_artifact_file(model_path, model_artifact)
        except (OSError, ArtifactError):
            model_state = "unsafe_drift"
        else:
            model_state = stored_model

    artifact_by_id = {
        artifact.artifact_id: artifact
        for artifact in artifacts.values()
    }
    verified_cache_artifacts: list[str] = []
    for artifact_id in downloaded:
        artifact = artifact_by_id.get(artifact_id)
        if artifact is None:
            continue
        try:
            _require_exact_artifact_file(
                download_cache_path(artifact, cache_dir),
                artifact,
            )
        except ArtifactError:
            continue
        verified_cache_artifacts.append(artifact_id)

    return {
        "portable": portable_state,
        "model": model_state,
        "verified_cache_artifacts": verified_cache_artifacts,
    }


def _validate_action_contract(scope: dict[str, object]) -> None:
    facts = scope.get("facts")
    artifacts = scope.get("artifacts")
    actions = scope.get("actions")
    if (
        not isinstance(facts, dict)
        or set(facts) != _FACT_FIELDS
        or not isinstance(artifacts, dict)
        or set(artifacts) != {"comfyui", "model"}
        or not isinstance(artifacts.get("comfyui"), dict)
        or not isinstance(artifacts.get("model"), dict)
        or not isinstance(actions, list)
    ):
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan facts, artifacts, or actions are invalid.",
        )
    portable_status = facts.get("portable_status")
    model_status = facts.get("model_status")
    if (
        facts.get("platform") != "win32"
        or facts.get("architecture") != "amd64"
        or facts.get("gpu_vendor") != "nvidia"
        or facts.get("gpu_generation") not in _SUPPORTED_GPU_GENERATIONS
        or type(facts.get("vram_bytes")) is not int
        or facts["vram_bytes"] <= 0
        or type(facts.get("windows_build")) is not int
        or facts["windows_build"] <= 0
        or type(facts.get("free_disk_bytes")) is not int
        or facts["free_disk_bytes"] <= 0
        or facts.get("network_allowed") is not True
        or facts.get("endpoint_ready") is not False
        or portable_status not in {"missing", "valid"}
        or model_status not in {"missing", "valid"}
    ):
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan facts are outside the executable Windows NVIDIA contract.",
        )
    comfyui_id = artifacts["comfyui"].get("artifact_id")
    model_id = artifacts["model"].get("artifact_id")
    if (
        not isinstance(comfyui_id, str)
        or not comfyui_id
        or not isinstance(model_id, str)
        or not model_id
    ):
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan artifact identities are invalid.",
        )

    expected: list[dict[str, object]] = []
    if portable_status == "valid":
        expected.append({"kind": "reuse_portable", "artifact_id": comfyui_id})
    else:
        expected.extend((
            {"kind": "download_comfyui", "artifact_id": comfyui_id},
            {"kind": "extract_comfyui", "artifact_id": comfyui_id},
        ))
    if model_status == "valid":
        expected.append({"kind": "reuse_model", "artifact_id": model_id})
    else:
        expected.extend((
            {"kind": "download_model", "artifact_id": model_id},
            {"kind": "install_model", "artifact_id": model_id},
        ))
    expected.append({"kind": "verify_install", "artifact_id": None})
    if actions != expected or portable_status == model_status == "valid":
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan actions do not match the frozen artifact facts.",
        )


def _normalize_artifacts(scope: dict[str, object]) -> dict[str, BootstrapArtifact]:
    artifacts = scope.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"comfyui", "model"}:
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan must contain exactly the frozen portable and model artifacts.",
        )
    normalized: dict[str, BootstrapArtifact] = {}
    for kind in ("comfyui", "model"):
        document = artifacts.get(kind)
        if not isinstance(document, dict) or set(document) != _ARTIFACT_FIELDS:
            raise StateError(
                "invalid_bootstrap_plan",
                "Bootstrap artifact has missing or unknown fields.",
            )
        try:
            artifact = BootstrapArtifact(**document)
        except (TypeError, ValueError) as error:
            raise StateError(
                "invalid_bootstrap_plan",
                "Bootstrap artifact could not be normalized.",
            ) from error
        if artifact.kind != kind:
            raise StateError(
                "invalid_bootstrap_plan",
                "Bootstrap artifact kind does not match its frozen scope slot.",
            )
        if (
            not isinstance(artifact.artifact_id, str)
            or _IDENTIFIER.fullmatch(artifact.artifact_id) is None
            or not _nonempty_string(artifact.version)
            or type(artifact.byte_size) is not int
            or not 0 < artifact.byte_size <= MAX_ARTIFACT_BYTES
            or not isinstance(artifact.sha256, str)
            or _SHA256.fullmatch(artifact.sha256) is None
            or not _nonempty_string(artifact.license_id)
            or not _valid_https_url(artifact.source_url, artifact.source_host)
            or not _valid_https_url(artifact.license_url)
            or not _valid_install_path(artifact.install_relative_path)
        ):
            raise StateError(
                "invalid_bootstrap_plan",
                "Bootstrap artifact metadata is outside the frozen safe contract.",
            )
        if kind == "comfyui" and (
            artifact.archive_format != "7z"
            or artifact.minimum_vram_gb is not None
            or "/" in artifact.install_relative_path
        ):
            raise StateError(
                "invalid_bootstrap_plan",
                "Bootstrap portable artifact metadata is invalid.",
            )
        if kind == "model" and (
            artifact.archive_format is not None
            or type(artifact.minimum_vram_gb) is not int
            or not 1 <= artifact.minimum_vram_gb <= 128
            or not artifact.install_relative_path.endswith(".safetensors")
        ):
            raise StateError(
                "invalid_bootstrap_plan",
                "Bootstrap model artifact metadata is invalid.",
            )
        normalized[kind] = artifact
    portable_root = normalized["comfyui"].install_relative_path
    expected_model_prefix = f"{portable_root}/ComfyUI/models/checkpoints/"
    if not normalized["model"].install_relative_path.startswith(expected_model_prefix):
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap model destination is outside the frozen portable root.",
        )
    return normalized


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_https_url(value: object, expected_host: str | None = None) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return bool(
        parsed.scheme == "https"
        and host
        and parsed.username is None
        and parsed.password is None
        and port is None
        and not parsed.query
        and not parsed.fragment
        and (expected_host is None or expected_host == host)
    )


def _valid_install_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return False
    for part in path.parts:
        if part.endswith((" ", ".")):
            return False
        base = part.split(".", 1)[0].upper()
        if base in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", base):
            return False
    return True


def _validate_scope_byte_contract(
    scope: dict[str, object],
    artifacts: dict[str, BootstrapArtifact],
) -> None:
    facts = scope.get("facts")
    if not isinstance(facts, dict):
        raise StateError("invalid_bootstrap_plan", "Bootstrap plan facts are invalid.")
    expected_download_bytes = 0
    if facts.get("portable_status") == "missing":
        expected_download_bytes += artifacts["comfyui"].byte_size
    if facts.get("model_status") == "missing":
        expected_download_bytes += artifacts["model"].byte_size
    required_disk_bytes = scope.get("required_disk_bytes")
    workflow = scope.get("workflow")
    if (
        not isinstance(scope.get("manifest_sha256"), str)
        or _SHA256.fullmatch(scope["manifest_sha256"]) is None
        or scope.get("reason") is not None
        or workflow != {
            "backend": "comfyui",
            "template_id": "sdxl-txt2img",
            "template_version": 1,
            "operation": "txt2img",
        }
        or type(scope.get("required_download_bytes")) is not int
        or scope["required_download_bytes"] != expected_download_bytes
        or type(required_disk_bytes) is not int
        or required_disk_bytes < expected_download_bytes
        or facts["free_disk_bytes"] < required_disk_bytes
        or facts["vram_bytes"] < (artifacts["model"].minimum_vram_gb or 0) * 1024**3
    ):
        raise StateError(
            "invalid_bootstrap_plan",
            "Bootstrap plan byte totals do not match its frozen artifact actions.",
        )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _result(status: str, plan_id: str, scope_sha256: str) -> dict[str, object]:
    return {
        "ok": True,
        "status": status,
        "plan_id": plan_id,
        "scope_sha256": scope_sha256,
    }
