from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import atomic_write_json
from .errors import ArtifactError, ConflictError, StateError, ValidationError
from .model_identity import (
    identity_token,
    validate_component_bundle,
    validate_discovery_record,
)


TRUST_SCHEMA_VERSION = 1
CATALOG_ID_PATTERN = re.compile(r"^local:[0-9a-f]{24}$")
TRUST_SCOPES = frozenset({"private", "public_candidate"})
OBSERVABLE_OPERATIONS = frozenset({"txt2img", "img2img", "inpaint"})
CREDENTIAL_KEYS = frozenset({
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "authorization",
    "credential",
    "credentials",
})
MAX_TRUST_BYTES = 4 * 1024 * 1024


def default_state_dir(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    override = values.get("LOCAL_GPU_IMAGEGEN_STATE_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = values.get("LOCALAPPDATA")
        return Path(base).expanduser() / "local-gpu-imagegen" if base else Path.home() / "AppData" / "Local" / "local-gpu-imagegen"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "local-gpu-imagegen"
    base = values.get("XDG_STATE_HOME")
    return Path(base).expanduser() / "local-gpu-imagegen" if base else Path.home() / ".local" / "state" / "local-gpu-imagegen"


class TrustRegistry:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "trust.json"

    def list_records(self) -> list[dict[str, object]]:
        return copy.deepcopy(self._read()["records"])

    def confirmation_value(
        self,
        action: str,
        record: dict[str, object],
        component_bundle: dict[str, object] | None = None,
    ) -> str:
        if action not in {"approve_private", "approve_public_candidate"}:
            raise ValidationError("invalid_trust_action", "Trust action is unsupported.")
        suffix = ""
        if component_bundle is not None:
            bundle = validate_component_bundle(component_bundle)
            suffix = f":bundle:{bundle['bundle_sha256']}"
        return f"{action}:{identity_token(record)}{suffix}"

    def approve_private(
        self,
        record: dict[str, object],
        confirmation: str,
        *,
        capabilities: dict[str, object],
        workflow_binding: dict[str, object] | None = None,
        component_bundle: dict[str, object] | None = None,
        preference: int = 0,
    ) -> dict[str, object]:
        return self._approve(
            "private",
            "approve_private",
            record,
            confirmation,
            capabilities,
            workflow_binding,
            component_bundle,
            preference,
            None,
        )

    def approve_public_candidate(
        self,
        record: dict[str, object],
        confirmation: str,
        *,
        metadata: dict[str, object],
        capabilities: dict[str, object] | None = None,
        workflow_binding: dict[str, object] | None = None,
        component_bundle: dict[str, object] | None = None,
        preference: int = 0,
    ) -> dict[str, object]:
        validated = validate_discovery_record(record)
        normalized_bundle = (
            validate_component_bundle(component_bundle)
            if component_bundle is not None
            else None
        )
        if (
            isinstance(workflow_binding, dict)
            and workflow_binding.get("backend") == "comfyui"
            and normalized_bundle is None
        ):
            raise ValidationError(
                "public_component_bundle_required",
                "Public ComfyUI candidates require a complete cryptographic component bundle.",
            )
        normalized_metadata = self._public_metadata(metadata, normalized_bundle)
        if validated["identity_strength"] != "cryptographic":
            raise ValidationError(
                "public_metadata_incomplete",
                "Public candidates require cryptographic identity and complete source/license metadata.",
            )
        return self._approve(
            "public_candidate",
            "approve_public_candidate",
            validated,
            confirmation,
            capabilities or {},
            workflow_binding,
            normalized_bundle,
            preference,
            normalized_metadata,
        )

    def revoke(
        self,
        catalog_id: str | None,
        identity: str,
        confirmation: str,
    ) -> dict[str, object]:
        if not isinstance(identity, str) or not identity.startswith("model:"):
            raise ValidationError("invalid_model_identity", "Identity token is invalid.")
        if catalog_id is not None and (
            not isinstance(catalog_id, str)
            or CATALOG_ID_PATTERN.fullmatch(catalog_id) is None
        ):
            raise ValidationError("invalid_catalog_id", "Catalog ID is invalid.")

        document = self._read()
        candidates = [
            entry
            for entry in document["records"]
            if entry["identity_token"] == identity
        ]
        if catalog_id is None:
            if len(candidates) > 1:
                raise ValidationError(
                    "ambiguous_trust_variant",
                    "Multiple workflow-bound trust variants require an exact catalog ID.",
                    {
                        "catalog_ids": sorted(
                            str(entry["catalog_id"]) for entry in candidates
                        )
                    },
                )
            if not candidates:
                raise StateError(
                    "trust_record_not_found",
                    "Trust record does not exist.",
                )
            catalog_id = str(candidates[0]["catalog_id"])
        elif not any(entry["catalog_id"] == catalog_id for entry in candidates):
            raise StateError("trust_record_not_found", "Trust record does not exist.")

        expected = f"revoke:{catalog_id}:{identity}"
        if confirmation != expected:
            raise ValidationError(
                "trust_confirmation_mismatch",
                "Trust confirmation does not match the displayed boundary.",
                {"confirmation": expected},
            )

        original_count = len(document["records"])
        document["records"] = [
            entry
            for entry in document["records"]
            if not (
                entry["catalog_id"] == catalog_id
                and entry["identity_token"] == identity
            )
        ]
        if len(document["records"]) == original_count:
            raise StateError("trust_record_not_found", "Trust record does not exist.")
        self._write(document)
        return {
            "catalog_id": catalog_id,
            "identity_token": identity,
            "revoked": True,
        }

    def record_observation(
        self,
        catalog_id: str,
        identity: str,
        operation: str,
        run_id: str,
    ) -> None:
        if operation not in OBSERVABLE_OPERATIONS:
            raise ValidationError("invalid_observed_operation", "Observed operation is unsupported.")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValidationError("invalid_observed_run", "Observed run ID must be non-empty.")
        document = self._read()
        record = next(
            (
                item
                for item in document["records"]
                if item["catalog_id"] == catalog_id
                and item["identity_token"] == identity
            ),
            None,
        )
        if record is None:
            raise StateError(
                "trust_record_not_found",
                "Cannot record evidence for an untrusted identity.",
            )
        evidence = {
            "level": "observed",
            "operation": operation,
            "run_id": run_id.strip(),
        }
        entries = record["evidence"]
        assert isinstance(entries, list)
        if evidence not in entries:
            entries.append(evidence)
            self._write(document)

    def _approve(
        self,
        scope: str,
        action: str,
        record: dict[str, object],
        confirmation: str,
        capabilities: dict[str, object],
        workflow_binding: dict[str, object] | None,
        component_bundle: dict[str, object] | None,
        preference: int,
        public_metadata: dict[str, object] | None,
    ) -> dict[str, object]:
        validated = validate_discovery_record(record)
        token = identity_token(validated)
        normalized_bundle = (
            validate_component_bundle(component_bundle)
            if component_bundle is not None
            else None
        )
        expected = self.confirmation_value(action, validated, normalized_bundle)
        if confirmation != expected:
            raise ValidationError(
                "trust_confirmation_mismatch",
                "Trust confirmation does not match the displayed boundary.",
                {"confirmation": expected},
            )
        if not isinstance(capabilities, dict):
            raise ValidationError("invalid_model_capabilities", "Capabilities must be an object.")
        if workflow_binding is not None and not isinstance(workflow_binding, dict):
            raise ValidationError("invalid_workflow_binding", "Workflow binding must be an object or null.")
        if type(preference) is not int or not -100 <= preference <= 100:
            raise ValidationError(
                "invalid_model_preference",
                "Model preference must be an integer from -100 to 100.",
            )

        candidate_values = {
            "identity_record": validated,
            "capabilities": capabilities,
            "workflow_binding": workflow_binding,
            "component_bundle": normalized_bundle,
            "public_metadata": public_metadata,
        }
        _reject_credentials(candidate_values)
        _validate_json(candidate_values, "invalid_trust_record")

        document = self._read()
        bundle_sha256 = (
            str(normalized_bundle["bundle_sha256"])
            if normalized_bundle is not None
            else None
        )
        previous = next(
            (
                item
                for item in document["records"]
                if item["identity_token"] == token
                and _bundle_sha(item) == bundle_sha256
            ),
            None,
        )
        if previous is not None:
            catalog_id = str(previous["catalog_id"])
        elif bundle_sha256 is not None:
            catalog_id = _variant_catalog_id(token, bundle_sha256)
        else:
            catalog_id = "local:" + token.removeprefix("model:")[:24]
        collision = next(
            (
                item
                for item in document["records"]
                if item["catalog_id"] == catalog_id
                and (
                    item["identity_token"] != token
                    or _bundle_sha(item) != bundle_sha256
                )
            ),
            None,
        )
        if collision is not None:
            raise ConflictError(
                "catalog_id_collision",
                "Derived workflow trust catalog ID collides with another record.",
            )
        evidence = copy.deepcopy(previous["evidence"]) if previous is not None else [{"level": "declared"}]
        limitations: list[str] = []
        if validated["identity_strength"] == "backend_binding":
            limitations.append(
                "Backend binding cannot detect same-name byte replacement."
            )
        approved: dict[str, object] = {
            "catalog_id": catalog_id,
            "identity_token": token,
            "identity_strength": validated["identity_strength"],
            "scope": scope,
            "identity_record": copy.deepcopy(validated),
            "capabilities": copy.deepcopy(capabilities),
            "workflow_binding": copy.deepcopy(workflow_binding),
            "component_bundle": copy.deepcopy(normalized_bundle),
            "preference": preference,
            "public_metadata": copy.deepcopy(public_metadata),
            "limitations": limitations,
            "evidence": evidence,
            "approved_at": _utc_now(),
        }
        records = [
            item
            for item in document["records"]
            if not (
                item["identity_token"] == token
                and _bundle_sha(item) == bundle_sha256
            )
        ]
        records.append(approved)
        records.sort(key=lambda item: (str(item["catalog_id"]), str(item["identity_token"])))
        document["records"] = records
        self._write(document)
        return copy.deepcopy(approved)

    @staticmethod
    def _public_metadata(
        value: object,
        component_bundle: dict[str, object] | None = None,
    ) -> dict[str, object]:
        required = {
            "source",
            "license_id",
            "license_url",
            "output_redistribution_status",
        }
        allowed = required | ({"components"} if component_bundle is not None else set())
        if not isinstance(value, dict) or set(value) != allowed:
            raise ValidationError(
                "public_metadata_incomplete",
                "Public candidate metadata fields are incomplete or unexpected.",
            )
        if any(not isinstance(value[field], str) or not value[field].strip() for field in required):
            raise ValidationError(
                "public_metadata_incomplete",
                "Public candidate metadata values must be non-empty strings.",
            )
        if value["output_redistribution_status"] != "approved":
            raise ValidationError(
                "public_metadata_incomplete",
                "Public candidate output redistribution must be explicitly approved.",
            )
        if component_bundle is not None:
            authorities = value.get("components")
            if not isinstance(authorities, list):
                raise ValidationError(
                    "public_metadata_incomplete",
                    "Public component authority must be an array.",
                )
            expected = {
                (str(item["role"]), str(item["sha256"]))
                for item in component_bundle["components"]
            }
            observed: set[tuple[str, str]] = set()
            fields = {
                "role",
                "sha256",
                "source",
                "license_id",
                "license_url",
                "output_redistribution_status",
            }
            for item in authorities:
                if (
                    not isinstance(item, dict)
                    or set(item) != fields
                    or any(
                        not isinstance(item[field], str) or not item[field].strip()
                        for field in fields
                    )
                    or item["output_redistribution_status"] != "approved"
                ):
                    raise ValidationError(
                        "public_metadata_incomplete",
                        "Every component requires exact source, license, hash, and redistribution authority.",
                    )
                observed.add((item["role"], item["sha256"]))
            if len(observed) != len(authorities) or observed != expected:
                raise ValidationError(
                    "public_metadata_incomplete",
                    "Public component authority does not match the cryptographic bundle.",
                )
        _reject_credentials(value)
        return copy.deepcopy(value)

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": TRUST_SCHEMA_VERSION, "records": []}
        try:
            if _link_like(self.path):
                raise OSError("link-like trust registry")
            file_stat = os.stat(self.path, follow_symlinks=False)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_TRUST_BYTES:
                raise OSError("unsafe trust registry")
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtifactError(
                "corrupt_trust_registry",
                "Local trust registry is unreadable or unsafe.",
            ) from error
        return _validate_document(value)

    def _write(self, document: dict[str, object]) -> None:
        validated = _validate_document(document)
        atomic_write_json(self.path, validated)


def _bundle_sha(record: dict[str, object]) -> str | None:
    bundle = record.get("component_bundle")
    if not isinstance(bundle, dict):
        return None
    digest = bundle.get("bundle_sha256")
    return str(digest) if isinstance(digest, str) else None


def _variant_catalog_id(identity: str, bundle_sha256: str) -> str:
    digest = hashlib.sha256(
        f"{identity}\n{bundle_sha256}".encode("utf-8")
    ).hexdigest()
    return "local:" + digest[:24]


def _validate_document(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "records"}
        or value.get("schema_version") != TRUST_SCHEMA_VERSION
        or type(value.get("schema_version")) is not int
        or not isinstance(value.get("records"), list)
    ):
        raise ArtifactError(
            "corrupt_trust_registry",
            "Local trust registry has an unsupported structure.",
        )
    document = copy.deepcopy(value)
    records = document["records"]
    assert isinstance(records, list)
    seen_pairs: set[tuple[str, str | None]] = set()
    seen_catalog_ids: dict[str, tuple[str, str | None]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ArtifactError("corrupt_trust_registry", "Trust record must be an object.")
        required = {
            "catalog_id",
            "identity_token",
            "identity_strength",
            "scope",
            "identity_record",
            "capabilities",
            "workflow_binding",
            "preference",
            "public_metadata",
            "limitations",
            "evidence",
            "approved_at",
        }
        if set(record) == required:
            record["component_bundle"] = None
        elif set(record) != required | {"component_bundle"}:
            raise ArtifactError("corrupt_trust_registry", "Trust record fields are invalid.")
        catalog_id = record["catalog_id"]
        token = record["identity_token"]
        if (
            not isinstance(catalog_id, str)
            or CATALOG_ID_PATTERN.fullmatch(catalog_id) is None
            or not isinstance(token, str)
            or not token.startswith("model:")
            or record["scope"] not in TRUST_SCOPES
        ):
            raise ArtifactError("corrupt_trust_registry", "Trust identity fields are invalid.")
        try:
            identity = validate_discovery_record(record["identity_record"])
        except ValidationError as error:
            raise ArtifactError("corrupt_trust_registry", "Stored model identity is invalid.") from error
        if identity_token(identity) != token or identity["identity_strength"] != record["identity_strength"]:
            raise ArtifactError("corrupt_trust_registry", "Stored identity token does not match its record.")
        if (
            not isinstance(record["capabilities"], dict)
            or record["workflow_binding"] is not None and not isinstance(record["workflow_binding"], dict)
            or type(record["preference"]) is not int
            or not -100 <= record["preference"] <= 100
            or not isinstance(record["limitations"], list)
            or not all(isinstance(item, str) for item in record["limitations"])
            or not isinstance(record["evidence"], list)
            or not isinstance(record["approved_at"], str)
        ):
            raise ArtifactError("corrupt_trust_registry", "Stored trust metadata is invalid.")
        component_bundle = record["component_bundle"]
        if component_bundle is not None:
            try:
                component_bundle = validate_component_bundle(component_bundle)
            except (ValidationError, ConflictError) as error:
                raise ArtifactError(
                    "corrupt_trust_registry",
                    "Stored component bundle is invalid.",
                ) from error
            record["component_bundle"] = component_bundle
        bundle_sha256 = _bundle_sha(record)
        legacy_catalog_id = "local:" + token.removeprefix("model:")[:24]
        variant_catalog_id = (
            _variant_catalog_id(token, bundle_sha256)
            if bundle_sha256 is not None
            else None
        )
        if catalog_id not in {legacy_catalog_id, variant_catalog_id}:
            raise ArtifactError(
                "corrupt_trust_registry",
                "Stored catalog ID does not match its identity and workflow bundle.",
            )
        if catalog_id != legacy_catalog_id and bundle_sha256 is None:
            raise ArtifactError(
                "corrupt_trust_registry",
                "Workflow variant catalog IDs require a component bundle.",
            )
        pair = (token, bundle_sha256)
        if pair in seen_pairs:
            raise ArtifactError(
                "corrupt_trust_registry",
                "Trust registry contains duplicate identity and bundle pairs.",
            )
        previous_pair = seen_catalog_ids.get(catalog_id)
        if previous_pair is not None and previous_pair != pair:
            raise ArtifactError(
                "corrupt_trust_registry",
                "Trust registry contains a catalog ID collision.",
            )
        seen_pairs.add(pair)
        seen_catalog_ids[catalog_id] = pair
        evidence = record["evidence"]
        assert isinstance(evidence, list)
        if not evidence or evidence[0] != {"level": "declared"}:
            raise ArtifactError("corrupt_trust_registry", "Stored evidence must begin at declared level.")
        for item in evidence[1:]:
            if (
                not isinstance(item, dict)
                or set(item) != {"level", "operation", "run_id"}
                or item.get("level") != "observed"
                or item.get("operation") not in OBSERVABLE_OPERATIONS
                or not isinstance(item.get("run_id"), str)
                or not item["run_id"].strip()
            ):
                raise ArtifactError("corrupt_trust_registry", "Stored observation evidence is invalid.")
        if record["scope"] == "public_candidate":
            if identity["identity_strength"] != "cryptographic":
                raise ArtifactError("corrupt_trust_registry", "Public candidate identity must be cryptographic.")
            try:
                TrustRegistry._public_metadata(record["public_metadata"], component_bundle)
            except ValidationError as error:
                raise ArtifactError("corrupt_trust_registry", "Stored public metadata is invalid.") from error
        elif record["public_metadata"] is not None:
            raise ArtifactError("corrupt_trust_registry", "Private trust cannot contain public metadata.")
        try:
            _reject_credentials(record)
        except ValidationError as error:
            raise ArtifactError("corrupt_trust_registry", "Stored trust data contains credentials.") from error
    _validate_json(document, "corrupt_trust_registry", artifact=True)
    return document


def _reject_credentials(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in CREDENTIAL_KEYS:
                raise ValidationError(
                    "credentials_not_allowed",
                    "Local BYOM state cannot store credentials.",
                )
            _reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_credentials(item)


def _validate_json(value: object, code: str, *, artifact: bool = False) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        if artifact:
            raise ArtifactError(code, "Local trust registry is not valid JSON data.") from error
        raise ValidationError(code, "Trust record must be JSON serializable.") from error


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    path_stat = os.lstat(path)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)
