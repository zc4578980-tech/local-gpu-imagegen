from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Collection
from urllib.parse import urlsplit

from .errors import ValidationError


MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024 * 1024
APPROVED_BOOTSTRAP_HOSTS = frozenset({"github.com", "huggingface.co"})

_ROOT_FIELDS = frozenset({
    "schema_version",
    "id",
    "platform",
    "architecture",
    "gpu_vendor",
    "minimum_windows_build",
    "minimum_free_disk_bytes",
    "minimum_nvidia_gpu_generation",
    "cuda_runtime",
    "comfyui",
    "model",
    "workflow",
})
_COMMON_ARTIFACT_FIELDS = frozenset({
    "id",
    "version",
    "source_url",
    "source_host",
    "license_id",
    "license_url",
    "byte_size",
    "sha256",
    "archive_format",
    "install_relative_path",
})
_MODEL_ARTIFACT_FIELDS = _COMMON_ARTIFACT_FIELDS | {"minimum_vram_gb"}
_WORKFLOW_FIELDS = frozenset({"backend", "template_id", "template_version", "operation"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class _DuplicateManifestKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BootstrapArtifact:
    kind: str
    artifact_id: str
    version: str
    source_url: str
    source_host: str
    byte_size: int
    sha256: str
    license_id: str
    license_url: str
    install_relative_path: str
    archive_format: str | None
    minimum_vram_gb: int | None = None


@dataclass(frozen=True, slots=True)
class BootstrapWorkflow:
    backend: str
    template_id: str
    template_version: int
    operation: str


@dataclass(frozen=True, slots=True)
class BootstrapManifest:
    schema_version: int
    manifest_id: str
    platform: str
    architecture: str
    gpu_vendor: str
    minimum_windows_build: int
    minimum_free_disk_bytes: int
    minimum_nvidia_gpu_generation: str
    cuda_runtime: str
    comfyui: BootstrapArtifact
    model: BootstrapArtifact
    workflow: BootstrapWorkflow
    manifest_sha256: str

    @property
    def required_download_bytes(self) -> int:
        return self.comfyui.byte_size + self.model.byte_size


def load_bootstrap_manifest(
    path: Path,
    *,
    allowed_hosts: Collection[str] = APPROVED_BOOTSTRAP_HOSTS,
) -> BootstrapManifest:
    manifest_path = Path(path)
    try:
        path_stat = manifest_path.lstat()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_size > MAX_MANIFEST_BYTES
            or bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)
        ):
            raise OSError("manifest is not a bounded regular file")
        raw = manifest_path.read_bytes()
        if len(raw) > MAX_MANIFEST_BYTES:
            raise OSError("manifest exceeds byte limit")
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _DuplicateManifestKey) as error:
        raise ValidationError(
            "invalid_bootstrap_manifest_json",
            "Bootstrap manifest must be a bounded UTF-8 JSON file.",
            {"path": str(manifest_path)},
        ) from error
    return validate_bootstrap_manifest(document, allowed_hosts=allowed_hosts)


def validate_bootstrap_manifest(
    document: object,
    *,
    allowed_hosts: Collection[str] = APPROVED_BOOTSTRAP_HOSTS,
) -> BootstrapManifest:
    if not isinstance(document, dict):
        raise ValidationError(
            "invalid_bootstrap_manifest",
            "Bootstrap manifest must be a JSON object.",
        )
    _require_fields(document, _ROOT_FIELDS, "invalid_bootstrap_manifest")

    if document["model"] is not None and not isinstance(document["model"], dict):
        raise ValidationError(
            "invalid_bootstrap_model_selection",
            "Bootstrap manifest must select exactly one default model.",
        )

    _validate_contract(document)
    normalized_hosts = frozenset(_normalize_allowed_hosts(allowed_hosts))
    comfyui = _validate_artifact(
        "comfyui",
        document["comfyui"],
        _COMMON_ARTIFACT_FIELDS,
        normalized_hosts,
    )
    model = _validate_artifact(
        "model",
        document["model"],
        _MODEL_ARTIFACT_FIELDS,
        normalized_hosts,
    )
    workflow = _validate_workflow(document["workflow"])

    if comfyui.archive_format != "7z" or model.archive_format is not None:
        raise ValidationError(
            "invalid_bootstrap_artifact",
            "The supported contract requires one 7z portable and one raw model file.",
        )
    if not model.install_relative_path.endswith(".safetensors"):
        raise ValidationError(
            "invalid_bootstrap_install_path",
            "The default model destination must be a safetensors checkpoint path.",
        )
    model_prefix = f"{comfyui.install_relative_path}/ComfyUI/models/checkpoints/"
    if not model.install_relative_path.startswith(model_prefix):
        raise ValidationError(
            "invalid_bootstrap_install_path",
            "The default model must be installed under the selected portable root.",
        )

    required_download_bytes = comfyui.byte_size + model.byte_size
    minimum_free_disk_bytes = document["minimum_free_disk_bytes"]
    if minimum_free_disk_bytes < required_download_bytes:
        raise ValidationError(
            "unsupported_bootstrap_contract",
            "The disk floor must cover all declared downloads.",
        )

    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return BootstrapManifest(
        schema_version=document["schema_version"],
        manifest_id=document["id"],
        platform=document["platform"],
        architecture=document["architecture"],
        gpu_vendor=document["gpu_vendor"],
        minimum_windows_build=document["minimum_windows_build"],
        minimum_free_disk_bytes=minimum_free_disk_bytes,
        minimum_nvidia_gpu_generation=document["minimum_nvidia_gpu_generation"],
        cuda_runtime=document["cuda_runtime"],
        comfyui=comfyui,
        model=model,
        workflow=workflow,
        manifest_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def _validate_contract(document: dict[str, object]) -> None:
    exact_values = {
        "schema_version": 1,
        "platform": "win32",
        "architecture": "amd64",
        "gpu_vendor": "nvidia",
        "minimum_nvidia_gpu_generation": "rtx-20-series",
        "cuda_runtime": "13.0",
    }
    if (
        type(document["schema_version"]) is not int
        or any(document[field] != expected for field, expected in exact_values.items())
    ):
        raise ValidationError(
            "unsupported_bootstrap_contract",
            "Only the frozen Windows x64 NVIDIA CUDA 13.0 contract is supported.",
        )
    if not _valid_identifier(document["id"]):
        raise ValidationError(
            "unsupported_bootstrap_contract",
            "Bootstrap manifest id is invalid.",
        )
    for field in ("minimum_windows_build", "minimum_free_disk_bytes"):
        value = document[field]
        if type(value) is not int or value <= 0:
            raise ValidationError(
                "unsupported_bootstrap_contract",
                f"{field} must be a positive integer.",
            )


def _validate_artifact(
    kind: str,
    value: object,
    required_fields: frozenset[str],
    allowed_hosts: frozenset[str],
) -> BootstrapArtifact:
    if not isinstance(value, dict):
        code = "invalid_bootstrap_model_selection" if kind == "model" else "invalid_bootstrap_artifact"
        raise ValidationError(code, f"{kind} must be exactly one artifact object.")
    _require_fields(value, required_fields, "invalid_bootstrap_artifact")

    if not _valid_identifier(value["id"]) or not _nonempty_string(value["version"]):
        raise ValidationError(
            "invalid_bootstrap_artifact",
            f"{kind} id and version must be non-empty canonical strings.",
        )
    byte_size = value["byte_size"]
    if type(byte_size) is not int or not 0 < byte_size <= MAX_ARTIFACT_BYTES:
        raise ValidationError(
            "invalid_bootstrap_artifact",
            f"{kind} byte_size is outside the supported range.",
        )
    digest = value["sha256"]
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValidationError(
            "invalid_bootstrap_artifact",
            f"{kind} sha256 must be exactly 64 lowercase hexadecimal characters.",
        )
    if not _nonempty_string(value["license_id"]) or not _nonempty_string(value["license_url"]):
        raise ValidationError(
            "invalid_bootstrap_artifact",
            f"{kind} requires explicit license metadata.",
        )

    source_host = _validate_https_url(
        value["source_url"],
        value["source_host"],
        allowed_hosts,
        "source",
    )
    _validate_https_url(value["license_url"], None, allowed_hosts, "license")
    install_path = _validate_install_path(value["install_relative_path"])

    minimum_vram_gb = value.get("minimum_vram_gb")
    if kind == "model" and (
        type(minimum_vram_gb) is not int or not 1 <= minimum_vram_gb <= 128
    ):
        raise ValidationError(
            "invalid_bootstrap_artifact",
            "model minimum_vram_gb must be an integer from 1 through 128.",
        )

    return BootstrapArtifact(
        kind=kind,
        artifact_id=value["id"],
        version=value["version"],
        source_url=value["source_url"],
        source_host=source_host,
        byte_size=byte_size,
        sha256=digest,
        license_id=value["license_id"],
        license_url=value["license_url"],
        install_relative_path=install_path,
        archive_format=value["archive_format"],
        minimum_vram_gb=minimum_vram_gb,
    )


def _validate_workflow(value: object) -> BootstrapWorkflow:
    if not isinstance(value, dict):
        raise ValidationError("invalid_bootstrap_workflow", "workflow must be an object.")
    _require_fields(value, _WORKFLOW_FIELDS, "invalid_bootstrap_workflow")
    expected = {
        "backend": "comfyui",
        "template_id": "sdxl-txt2img",
        "template_version": 1,
        "operation": "txt2img",
    }
    if type(value["template_version"]) is not int or value != expected:
        raise ValidationError(
            "invalid_bootstrap_workflow",
            "Only the shipped SDXL txt2img workflow binding is supported.",
        )
    return BootstrapWorkflow(**value)


def _require_fields(value: dict[str, object], required: frozenset[str], missing_code: str) -> None:
    unknown = sorted(set(value) - required)
    if unknown:
        raise ValidationError(
            "unknown_bootstrap_manifest_fields",
            "Bootstrap manifest contains unknown fields.",
            {"fields": unknown},
        )
    missing = sorted(required - set(value))
    if missing:
        raise ValidationError(
            missing_code,
            "Bootstrap manifest is missing required fields.",
            {"fields": missing},
        )


def _validate_https_url(
    url: object,
    declared_host: object,
    allowed_hosts: frozenset[str],
    purpose: str,
) -> str:
    if not isinstance(url, str):
        raise ValidationError("invalid_bootstrap_source", f"{purpose} URL must be a string.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValidationError("invalid_bootstrap_source", f"{purpose} URL is malformed.") from error
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or host not in allowed_hosts
    ):
        raise ValidationError(
            "invalid_bootstrap_source",
            f"{purpose} URL must use an approved HTTPS host without credentials or redirects.",
            {"host": host},
        )
    if declared_host is not None and declared_host != host:
        raise ValidationError(
            "invalid_bootstrap_source",
            "Declared source_host must exactly match the URL hostname.",
        )
    return host


def _validate_install_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValidationError(
            "invalid_bootstrap_install_path",
            "Install path must be a normalized relative POSIX path.",
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or str(path) != value:
        raise ValidationError(
            "invalid_bootstrap_install_path",
            "Install path must stay inside the selected bootstrap root.",
        )
    return value


def _normalize_allowed_hosts(hosts: Collection[str]) -> tuple[str, ...]:
    normalized = tuple(host.lower() for host in hosts if isinstance(host, str) and host)
    if not normalized:
        raise ValidationError("invalid_bootstrap_source", "At least one source host must be approved.")
    return normalized


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateManifestKey(key)
        value[key] = item
    return value


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
