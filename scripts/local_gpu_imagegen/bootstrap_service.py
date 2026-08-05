from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlsplit

from .bootstrap_catalog import MAX_ARTIFACT_BYTES, BootstrapArtifact
from .bootstrap_download import download_verified
from .errors import StateError, ValidationError


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
_MAX_STATE_BYTES = 512 * 1024


class _DuplicateStateKey(ValueError):
    pass


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
    expected_downloaded_artifacts = tuple(
        normalized_artifacts[action["kind"].removeprefix("download_")].artifact_id
        for action in scope["actions"]
        if action["kind"] in {"download_comfyui", "download_model"}
    )

    transaction_path = root / f"{plan_id}.transaction.json"
    existing_result = _existing_transaction_result(
        transaction_path,
        plan_id,
        scope_sha256,
        confirmation,
        expected_downloaded_artifacts,
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
        )
        if existing_result is not None:
            return existing_result
        transaction = {
            "schema_version": 1,
            "plan_id": plan_id,
            "scope_sha256": scope_sha256,
            "confirmation_sha256": _sha256_text(confirmation),
            "status": "in_progress",
            "downloaded_artifacts": [],
        }
        _atomic_write_state(transaction_path, transaction, root, root_stat)

        downloaded: list[str] = []
        actions = scope["actions"]
        try:
            for action in actions:
                kind = action["kind"]
                if kind not in {"download_comfyui", "download_model"}:
                    continue
                artifact_kind = kind.removeprefix("download_")
                artifact = normalized_artifacts[artifact_kind]
                downloader(artifact, root.parent / "cache")
                downloaded.append(artifact.artifact_id)
        except Exception:
            transaction["status"] = "failed"
            transaction["downloaded_artifacts"] = downloaded
            _atomic_write_state(transaction_path, transaction, root, root_stat)
            raise

        transaction["status"] = "completed"
        transaction["downloaded_artifacts"] = downloaded
        _atomic_write_state(transaction_path, transaction, root, root_stat)
        return _result("installed", plan_id, scope_sha256)
    finally:
        try:
            claim_path.rmdir()
        except OSError:
            pass


def _existing_transaction_result(
    transaction_path: Path,
    plan_id: str,
    scope_sha256: str,
    confirmation: str,
    expected_downloaded_artifacts: tuple[str, ...],
) -> dict[str, object] | None:
    if not os.path.lexists(transaction_path):
        return None
    transaction = _read_json(transaction_path, "invalid_bootstrap_transaction")
    _validate_transaction(
        transaction,
        plan_id,
        scope_sha256,
        confirmation,
        expected_downloaded_artifacts,
    )
    if transaction["status"] == "completed":
        return _result("already_installed", plan_id, scope_sha256)
    raise StateError(
        "bootstrap_confirmation_consumed",
        "Bootstrap confirmation has already been consumed by another transaction state.",
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
) -> None:
    downloaded = transaction.get("downloaded_artifacts")
    if (
        set(transaction) != _TRANSACTION_FIELDS
        or transaction.get("schema_version") != 1
        or transaction.get("plan_id") != plan_id
        or transaction.get("scope_sha256") != scope_sha256
        or transaction.get("confirmation_sha256") != _sha256_text(confirmation)
        or transaction.get("status") not in {"in_progress", "failed", "completed"}
        or not isinstance(downloaded, list)
        or any(not isinstance(item, str) or not item for item in downloaded)
        or len(downloaded) != len(set(downloaded))
        or (
            transaction.get("status") == "completed"
            and tuple(downloaded) != expected_downloaded_artifacts
        )
        or (
            transaction.get("status") in {"in_progress", "failed"}
            and tuple(downloaded) != expected_downloaded_artifacts[:len(downloaded)]
        )
    ):
        raise StateError(
            "invalid_bootstrap_transaction",
            "Bootstrap transaction record does not match the exact frozen plan.",
        )


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
