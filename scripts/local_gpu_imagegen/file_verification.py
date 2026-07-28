from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import atomic_write_json
from .errors import ArtifactError, ValidationError
from .trust_registry import _link_like, _reject_credentials


DOCUMENT_FIELDS = {"schema_version", "records"}
RECORD_FIELDS = {
    "authorization_id", "local_path", "resolved_root", "backend_model_id",
    "sha256", "byte_size", "modified_ns", "status", "created_at", "last_verified_at",
}
STATUSES = {"active", "drifted", "revoked"}
CREDENTIAL_KEYS = {
    "api_key", "apikey", "token", "password", "secret",
    "authorization", "credential", "credentials",
}


class FileVerificationRegistry:
    def __init__(self, state_dir: Path, *, now: Callable[[], str] | None = None) -> None:
        resolved = Path(state_dir).expanduser().resolve()
        allowed = [Path.home().resolve()]
        for variable in ("LOCALAPPDATA", "XDG_STATE_HOME"):
            value = os.environ.get(variable)
            if value:
                allowed.append(Path(value).expanduser().resolve())
        if str(resolved).startswith("\\\\") or not any(_within(resolved, root) for root in allowed):
            raise ValidationError("invalid_file_verification_state_dir", "File verification state must be user-local.")
        self.path = resolved / "file-verifications.json"
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    def resolve(
        self,
        *,
        backend_model_id: str | None = None,
        authorization_id: str | None = None,
        active_only: bool = True,
    ) -> dict[str, object] | None:
        if not backend_model_id and not authorization_id:
            raise ValidationError("invalid_file_verification_lookup", "An authorization ID or backend model ID is required.")
        matches = [
            record for record in self._read()["records"]
            if (not active_only or record["status"] == "active")
            and (authorization_id is None or record["authorization_id"] == authorization_id)
            and (backend_model_id is None or record["backend_model_id"] == backend_model_id)
        ]
        if len(matches) > 1:
            raise ValidationError("ambiguous_file_verification", "Multiple exact files match this backend model name.")
        return copy.deepcopy(matches[0]) if matches else None

    def record_verified(
        self,
        *,
        local_path: Path,
        resolved_root: Path,
        backend_model_id: str,
        fingerprint: dict[str, object],
    ) -> dict[str, object]:
        if set(fingerprint) != {"sha256", "byte_size", "modified_ns"}:
            raise ValidationError("invalid_file_fingerprint", "Fingerprint contains unsupported fields.")
        boundary = {
            "local_path": str(Path(local_path).resolve()),
            "resolved_root": str(Path(resolved_root).resolve()),
            "backend_model_id": backend_model_id,
        }
        authorization_id = "verification:" + _canonical_hash(boundary)[:24]
        document = self._read()
        prior = next((item for item in document["records"] if item["authorization_id"] == authorization_id), None)
        timestamp = self.now()
        record = _validate_record({
            "authorization_id": authorization_id,
            **boundary,
            "sha256": fingerprint.get("sha256"),
            "byte_size": fingerprint.get("byte_size"),
            "modified_ns": fingerprint.get("modified_ns"),
            "status": "active",
            "created_at": prior["created_at"] if prior else timestamp,
            "last_verified_at": timestamp,
        })
        document["records"] = [item for item in document["records"] if item["authorization_id"] != authorization_id] + [record]
        self._write(document)
        return copy.deepcopy(record)

    def set_status(self, authorization_id: str, status: str) -> dict[str, object]:
        if status not in {"drifted", "revoked"}:
            raise ValidationError("invalid_file_verification_status", "File verification status is unsupported.")
        document = self._read()
        matches = [item for item in document["records"] if item["authorization_id"] == authorization_id]
        if len(matches) != 1:
            raise ValidationError("file_verification_not_found", "File verification authorization does not exist.")
        matches[0]["status"] = status
        self._write(document)
        return copy.deepcopy(matches[0])

    def _read(self) -> dict[str, object]:
        if not os.path.lexists(self.path):
            return {"schema_version": 1, "records": []}
        try:
            file_stat = os.stat(self.path, follow_symlinks=False)
            if _link_like(self.path) or not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > 4 * 1024 * 1024:
                raise ValueError("unsafe registry file")
            return _validate_document(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ArtifactError(
                "corrupt_file_verification_registry",
                "File verification registry is corrupt.",
            ) from error

    def _write(self, document: dict[str, object]) -> None:
        atomic_write_json(self.path, _validate_document(document))


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    file_stat = os.lstat(path)
    attributes = getattr(file_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _reject_credentials(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in CREDENTIAL_KEYS:
                raise ValueError("credential field")
            _reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_credentials(item)


def _validate_record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != RECORD_FIELDS:
        raise ValueError("record fields")
    _reject_credentials(value)
    if re.fullmatch(r"verification:[0-9a-f]{24}", str(value["authorization_id"])) is None:
        raise ValueError("authorization ID")
    local_path = Path(str(value["local_path"]))
    root = Path(str(value["resolved_root"]))
    if not local_path.is_absolute() or not root.is_absolute() or local_path != local_path.resolve() or root != root.resolve() or str(local_path).startswith("\\\\") or str(root).startswith("\\\\") or not _within(local_path, root):
        raise ValueError("non-local path")
    if not isinstance(value["backend_model_id"], str) or not value["backend_model_id"].strip():
        raise ValueError("backend model ID")
    boundary = {
        "local_path": str(local_path), "resolved_root": str(root),
        "backend_model_id": value["backend_model_id"],
    }
    if value["authorization_id"] != "verification:" + _canonical_hash(boundary)[:24]:
        raise ValueError("authorization boundary")
    if re.fullmatch(r"[0-9a-f]{64}", str(value["sha256"])) is None:
        raise ValueError("SHA-256")
    if any(type(value[field]) is not int or value[field] < 0 for field in ("byte_size", "modified_ns")):
        raise ValueError("stat boundary")
    if value["status"] not in STATUSES:
        raise ValueError("status")
    if any(re.fullmatch(r"\d{4}-\d{2}-\d{2}T.+Z", str(value[field])) is None for field in ("created_at", "last_verified_at")):
        raise ValueError("timestamp")
    return copy.deepcopy(value)


def _validate_document(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != DOCUMENT_FIELDS or value.get("schema_version") != 1 or not isinstance(value.get("records"), list):
        raise ValueError("document shape")
    records = [_validate_record(item) for item in value["records"]]
    identifiers = [str(item["authorization_id"]) for item in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate authorization ID")
    return {"schema_version": 1, "records": records}
