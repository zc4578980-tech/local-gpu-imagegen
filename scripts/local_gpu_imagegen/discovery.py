from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import stat
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .backends.base import BackendRegistry
from .errors import ConflictError, ValidationError
from .model_identity import (
    fingerprint_selected_file,
    identity_token,
    validate_discovery_record,
)


DISCOVERY_MODES = frozenset({
    "api_only",
    "selected_folders",
    "common_locations",
    "full_drive",
})
DISCOVERY_STAGES = frozenset({"index", "fingerprint"})
MODEL_EXTENSIONS = (".ckpt", ".safetensors")
DEFAULT_EXCLUSIONS = (
    "$Recycle.Bin",
    "System Volume Information",
    "Windows",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "site-packages",
)
MAX_SAFETENSORS_HEADER_BYTES = 16 * 1024 * 1024
MAX_SIDECAR_BYTES = 1024 * 1024


CancelCallback = Callable[[], bool]
ProgressCallback = Callable[[dict[str, int]], None]
RootsProvider = Callable[[], Iterable[Path | str]]
RootPredicate = Callable[[Path], bool]


class DiscoveryService:
    def __init__(
        self,
        adapters: BackendRegistry,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = 300,
        common_roots_provider: RootsProvider | None = None,
        network_root_detector: RootPredicate | None = None,
        drive_root_validator: RootPredicate | None = None,
    ) -> None:
        if not isinstance(adapters, BackendRegistry):
            raise ValidationError(
                "invalid_discovery_registry",
                "Discovery requires a backend registry.",
            )
        if not callable(clock):
            raise ValidationError("invalid_discovery_clock", "Discovery clock must be callable.")
        if (
            not isinstance(ttl_seconds, (int, float))
            or isinstance(ttl_seconds, bool)
            or ttl_seconds <= 0
        ):
            raise ValidationError(
                "invalid_discovery_ttl",
                "Discovery plan lifetime must be positive.",
            )
        self.adapters = adapters
        self.clock = clock
        self.ttl_seconds = float(ttl_seconds)
        self.common_roots_provider = common_roots_provider or _common_model_roots
        self.network_root_detector = network_root_detector or _network_root
        self.drive_root_validator = drive_root_validator or _drive_root
        self._plans: dict[str, dict[str, object]] = {}
        self._inventory: list[dict[str, object]] = []

    def plan(self, request: dict[str, object]) -> dict[str, object]:
        normalized, frozen_candidates = self._normalize_plan_request(request)
        scope_hash = _canonical_hash(normalized)
        plan_id = secrets.token_hex(12)
        value: dict[str, object] = {
            **normalized,
            "plan_id": plan_id,
            "scope_hash": scope_hash,
            "expires_at": self.clock() + self.ttl_seconds,
            "confirmation": f"scan:{plan_id}:{scope_hash}",
        }
        network_roots = normalized["network_roots"]
        if network_roots:
            network_hash = _canonical_hash({"roots": network_roots})
            value["network_confirmation"] = f"network-scan:{plan_id}:{network_hash}"
        stored = copy.deepcopy(value)
        stored["_frozen_candidates"] = frozen_candidates
        self._plans[plan_id] = stored
        return copy.deepcopy(value)

    def execute(
        self,
        plan_id: str,
        confirmation: str,
        *,
        network_confirmation: str | None = None,
        cancel: CancelCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, object]:
        if not isinstance(plan_id, str) or not plan_id:
            raise ValidationError(
                "invalid_discovery_plan",
                "Discovery plan ID must be a non-empty string.",
            )
        if cancel is not None and not callable(cancel):
            raise ValidationError(
                "invalid_discovery_callback",
                "Discovery cancellation callback must be callable.",
            )
        if progress is not None and not callable(progress):
            raise ValidationError(
                "invalid_discovery_callback",
                "Discovery progress callback must be callable.",
            )

        plan = self._current_plan(plan_id, confirmation, network_confirmation)
        del self._plans[plan_id]
        if plan["mode"] == "api_only":
            candidates = self._api_candidates(plan)
            incomplete = False
        elif plan["stage"] == "index":
            candidates, incomplete = self._filesystem_candidates(plan, cancel, progress)
        else:
            candidates = self._fingerprint_selected(plan)
            incomplete = False

        for candidate in candidates:
            candidate["trusted"] = False
            candidate["incomplete"] = incomplete
        self._inventory = _merge_inventory(self._inventory, candidates)
        return {
            "plan_id": plan_id,
            "scope_hash": plan["scope_hash"],
            "incomplete": incomplete,
            "candidates": copy.deepcopy(candidates),
            "trusted": False,
        }

    def inventory(self) -> list[dict[str, object]]:
        return copy.deepcopy(self._inventory)

    def _normalize_plan_request(
        self,
        request: dict[str, object],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        if not isinstance(request, dict):
            raise ValidationError(
                "invalid_discovery_plan",
                "Discovery plan request must be an object.",
            )
        mode = request.get("mode", "api_only")
        stage = request.get("stage", "index")
        if mode not in DISCOVERY_MODES:
            raise ValidationError(
                "invalid_discovery_mode",
                "Discovery mode is unsupported.",
            )
        if stage not in DISCOVERY_STAGES:
            raise ValidationError(
                "invalid_discovery_stage",
                "Discovery stage is unsupported.",
            )

        selected_candidates = _string_list(
            request.get("selected_candidates", []),
            "selected_candidates",
        )
        explicit_includes = _resolved_paths(
            request.get("explicit_includes", []),
            "explicit_includes",
        )
        if stage == "index" and selected_candidates:
            raise ValidationError(
                "invalid_discovery_plan",
                "Index plans cannot select fingerprint candidates.",
            )
        if stage == "fingerprint" and not selected_candidates:
            raise ValidationError(
                "invalid_discovery_plan",
                "Fingerprint plans require selected candidates.",
            )

        if mode == "api_only":
            if stage != "index" or selected_candidates or explicit_includes:
                raise ValidationError(
                    "invalid_discovery_plan",
                    "API discovery supports only the index stage.",
                )
            roots: list[str] = []
            backends = _string_list(
                request.get("backends", list(self.adapters.adapter_ids())),
                "backends",
            )
            if not backends:
                raise ValidationError(
                    "invalid_discovery_plan",
                    "API discovery requires at least one registered backend.",
                )
            endpoint_records: list[dict[str, str]] = []
            for backend_id in sorted(set(backends)):
                adapter = self.adapters.get(backend_id)
                endpoint_identity = getattr(adapter, "endpoint_identity", None)
                if not isinstance(endpoint_identity, str) or not endpoint_identity:
                    raise ValidationError(
                        "invalid_backend_adapter",
                        "Discovery adapter must expose an endpoint identity.",
                        {"backend": backend_id},
                    )
                endpoint_records.append({
                    "backend": backend_id,
                    "endpoint_identity": endpoint_identity,
                })
            backends = [item["backend"] for item in endpoint_records]
        else:
            if request.get("backends") not in (None, []):
                raise ValidationError(
                    "invalid_discovery_plan",
                    "Filesystem discovery does not accept backend adapters.",
                )
            endpoint_records = []
            backends = []
            if mode == "common_locations":
                if request.get("roots") not in (None, []):
                    raise ValidationError(
                        "invalid_discovery_plan",
                        "Common-location roots are proposed by the discovery service.",
                    )
                roots = _resolved_paths(
                    list(self.common_roots_provider()),
                    "roots",
                )
            else:
                roots = _resolved_paths(request.get("roots", []), "roots")
            if not roots:
                raise ValidationError(
                    "invalid_discovery_plan",
                    "Filesystem discovery requires at least one root.",
                )
            if mode == "full_drive":
                for root_value in roots:
                    if not self.drive_root_validator(Path(root_value)):
                        raise ValidationError(
                            "invalid_drive_root",
                            "Full-drive discovery requires exact drive roots.",
                        )
            for include in explicit_includes:
                if not any(_within(Path(include), Path(root)) for root in roots):
                    raise ValidationError(
                        "invalid_discovery_include",
                        "Explicit discovery includes must stay inside a selected root.",
                    )

        network_roots = [
            root for root in roots if self.network_root_detector(Path(root))
        ]
        frozen_candidates: list[dict[str, object]] = []
        if stage == "fingerprint":
            by_id = {
                item.get("candidate_id"): item
                for item in self._inventory
                if isinstance(item.get("candidate_id"), str)
            }
            for candidate_id in selected_candidates:
                candidate = by_id.get(candidate_id)
                if candidate is None:
                    raise ValidationError(
                        "unknown_discovery_candidate",
                        "Selected discovery candidate is not in the retained inventory.",
                    )
                root_value = candidate.get("resolved_root")
                local_path = candidate.get("local_path")
                if (
                    not isinstance(root_value, str)
                    or root_value not in roots
                    or not isinstance(local_path, str)
                    or not _within(Path(local_path), Path(root_value))
                ):
                    raise ValidationError(
                        "unknown_discovery_candidate",
                        "Selected discovery candidate is outside the unchanged roots.",
                    )
                frozen_candidates.append(copy.deepcopy(candidate))

        cost_warning = (
            "Index reads bounded metadata only; full model hashes are deferred to "
            "selected fingerprint candidates."
            if stage == "index"
            else "Fingerprint hashes only the exact selected model files and may read "
            "their complete contents."
        )
        normalized: dict[str, object] = {
            "mode": mode,
            "scan_mode": mode,
            "stage": stage,
            "backends": backends,
            "endpoints": endpoint_records,
            "roots": roots,
            "network_roots": network_roots,
            "selected_candidates": selected_candidates,
            "extensions": list(MODEL_EXTENSIONS),
            "exclusions": list(DEFAULT_EXCLUSIONS),
            "explicit_includes": explicit_includes,
            "cost_warning": cost_warning,
        }
        return normalized, frozen_candidates

    def _current_plan(
        self,
        plan_id: str,
        confirmation: str,
        network_confirmation: str | None,
    ) -> dict[str, object]:
        stored = self._plans.get(plan_id)
        if stored is None:
            raise ConflictError(
                "discovery_plan_unavailable",
                "Discovery plan is unavailable or already consumed.",
            )
        if self.clock() > float(stored["expires_at"]):
            del self._plans[plan_id]
            raise ConflictError(
                "discovery_plan_expired",
                "Discovery plan expired before execution.",
            )
        if confirmation != stored["confirmation"]:
            raise ValidationError(
                "discovery_confirmation_mismatch",
                "Discovery execution requires the exact displayed confirmation.",
            )
        expected_network = stored.get("network_confirmation")
        if expected_network is not None and network_confirmation != expected_network:
            raise ValidationError(
                "network_scan_confirmation_required",
                "Network-root discovery requires its separate exact confirmation.",
                {"confirmation": expected_network},
            )
        scope = {
            key: value
            for key, value in stored.items()
            if key not in {
                "plan_id",
                "scope_hash",
                "expires_at",
                "confirmation",
                "network_confirmation",
                "_frozen_candidates",
            }
        }
        if _canonical_hash(scope) != stored["scope_hash"]:
            del self._plans[plan_id]
            raise ConflictError(
                "discovery_plan_changed",
                "Discovery plan changed after it was displayed.",
            )
        return copy.deepcopy(stored)

    def _api_candidates(self, plan: dict[str, object]) -> list[dict[str, object]]:
        records = self.adapters.discover_all(plan["backends"])
        candidates: list[dict[str, object]] = []
        for record in records:
            validated = validate_discovery_record(record)
            token = identity_token(validated)
            candidate = {
                **validated,
                "identity_token": token,
                "candidate_id": "candidate:" + _canonical_hash({"identity_token": token}),
                "source_type": "api",
                "trusted": False,
            }
            candidates.append(candidate)
        return sorted(candidates, key=lambda item: str(item["candidate_id"]))

    def _filesystem_candidates(
        self,
        plan: dict[str, object],
        cancel: CancelCallback | None,
        progress: ProgressCallback | None,
    ) -> tuple[list[dict[str, object]], bool]:
        candidates: list[dict[str, object]] = []
        counters = {"visited_directories": 0, "visited_files": 0, "candidates": 0}
        for root_value in plan["roots"]:
            root = Path(root_value)
            if not root.is_dir() or _link_like(root):
                raise ValidationError(
                    "discovery_root_unavailable",
                    "Discovery root must be an accessible non-link directory.",
                )
            queue = [root]
            while queue:
                if _cancelled(cancel):
                    return candidates, True
                directory = queue.pop()
                if directory != root and (
                    _link_like(directory) or not _within(directory, root)
                ):
                    continue
                counters["visited_directories"] += 1
                _report(progress, counters)
                try:
                    with os.scandir(directory) as iterator:
                        entries = sorted(iterator, key=lambda entry: entry.name.lower())
                except OSError as error:
                    raise ValidationError(
                        "discovery_root_unavailable",
                        "Discovery could not read a selected directory.",
                    ) from error
                for entry in entries:
                    if _cancelled(cancel):
                        return candidates, True
                    path = Path(entry.path)
                    if _link_like(path) or not _within(path, root):
                        continue
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(entry_stat.st_mode):
                        if not _excluded(
                            path,
                            root,
                            plan["explicit_includes"],
                        ):
                            queue.append(path)
                        continue
                    if not stat.S_ISREG(entry_stat.st_mode):
                        continue
                    counters["visited_files"] += 1
                    if path.suffix.lower() not in MODEL_EXTENSIONS:
                        _report(progress, counters)
                        continue
                    candidate = _index_candidate(path, root, entry_stat)
                    candidates.append(candidate)
                    counters["candidates"] += 1
                    _report(progress, counters)
        return candidates, False

    def _fingerprint_selected(self, plan: dict[str, object]) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for indexed in plan["_frozen_candidates"]:
            path = Path(str(indexed["local_path"]))
            fingerprint = fingerprint_selected_file(path, indexed)
            record = validate_discovery_record({
                **indexed,
                "backend": "filesystem",
                "endpoint_identity": "filesystem:"
                + _canonical_hash({"root": indexed["resolved_root"]}),
                "backend_model_id": indexed["relative_path"],
                "sha256": fingerprint["sha256"],
                "byte_size": fingerprint["byte_size"],
                "modified_ns": fingerprint["modified_ns"],
                "identity_strength": "cryptographic",
            })
            record.update({
                "candidate_id": indexed["candidate_id"],
                "source_type": "filesystem",
                "resolved_root": indexed["resolved_root"],
                "local_path": indexed["local_path"],
                "relative_path": indexed["relative_path"],
                "filename": indexed["filename"],
                "trusted": False,
            })
            record["identity_token"] = identity_token(record)
            candidates.append(record)
        return candidates


def _index_candidate(path: Path, root: Path, file_stat: os.stat_result) -> dict[str, object]:
    if _link_like(path) or not stat.S_ISREG(file_stat.st_mode):
        raise ValidationError(
            "unsafe_discovery_entry",
            "Discovery candidate must be a regular non-link file.",
        )
    relative = path.relative_to(root)
    metadata = _read_safetensors_metadata(path) if path.suffix.lower() == ".safetensors" else {}
    metadata.update(_read_bounded_sidecar(path.with_suffix(".json")))
    boundary = {
        "resolved_root": str(root),
        "relative_path": str(relative),
        "byte_size": file_stat.st_size,
        "modified_ns": file_stat.st_mtime_ns,
    }
    return {
        **boundary,
        "candidate_id": "candidate:" + _canonical_hash(boundary),
        "source_type": "filesystem",
        "local_path": str(path),
        "filename": path.name,
        "format": path.suffix.lower(),
        "metadata": metadata,
        "sha256": None,
        "identity_strength": None,
        "trusted": False,
    }


def _read_safetensors_metadata(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as stream:
            size_bytes = stream.read(8)
            if len(size_bytes) != 8:
                return {}
            header_size = int.from_bytes(size_bytes, "little")
            if not 2 <= header_size <= MAX_SAFETENSORS_HEADER_BYTES:
                return {}
            encoded = stream.read(header_size)
            if len(encoded) != header_size:
                return {}
        document = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}
    metadata = document.get("__metadata__", {}) if isinstance(document, dict) else {}
    return copy.deepcopy(metadata) if isinstance(metadata, dict) else {}


def _read_bounded_sidecar(path: Path) -> dict[str, object]:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
        if (
            _link_like(path)
            or not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_size > MAX_SIDECAR_BYTES
        ):
            return {}
        with path.open("rb") as stream:
            encoded = stream.read(MAX_SIDECAR_BYTES + 1)
        if len(encoded) > MAX_SIDECAR_BYTES:
            return {}
        value = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValidationError(
            "invalid_discovery_plan",
            f"Discovery {field} must be an array of non-empty strings.",
        )
    stripped = [item.strip() for item in value]
    if len(set(stripped)) != len(stripped):
        raise ValidationError(
            "invalid_discovery_plan",
            f"Discovery {field} must not contain duplicates.",
        )
    return stripped


def _resolved_paths(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, (str, Path)) or not str(item).strip() for item in value
    ):
        raise ValidationError(
            "invalid_discovery_plan",
            f"Discovery {field} must be an array of non-empty paths.",
        )
    resolved = [str(Path(item).expanduser().resolve()) for item in value]
    if len(set(resolved)) != len(resolved):
        raise ValidationError(
            "invalid_discovery_plan",
            f"Discovery {field} must not contain duplicate paths.",
        )
    return resolved


def _within(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    return True


def _link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        path_stat = os.lstat(path)
    except OSError:
        return True
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _excluded(
    path: Path,
    root: Path,
    explicit_includes: object,
) -> bool:
    includes = [Path(item) for item in explicit_includes]
    if any(_within(path, include) or _within(include, path) for include in includes):
        return False
    relative = path.relative_to(root)
    return any(part.lower() in {item.lower() for item in DEFAULT_EXCLUSIONS} for part in relative.parts)


def _cancelled(cancel: CancelCallback | None) -> bool:
    return bool(cancel is not None and cancel())


def _report(progress: ProgressCallback | None, counters: dict[str, int]) -> None:
    if progress is not None:
        progress(dict(counters))


def _merge_inventory(
    existing: list[dict[str, object]],
    incoming: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged = copy.deepcopy(existing)
    positions = {
        item.get("candidate_id"): index
        for index, item in enumerate(merged)
        if isinstance(item.get("candidate_id"), str)
    }
    for candidate in incoming:
        candidate_id = candidate["candidate_id"]
        if candidate_id in positions:
            merged[positions[candidate_id]] = copy.deepcopy(candidate)
        else:
            positions[candidate_id] = len(merged)
            merged.append(copy.deepcopy(candidate))
    return merged


def _common_model_roots() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("LOCALAPPDATA", "USERPROFILE"):
        base = os.environ.get(variable)
        if base:
            candidates.extend((
                Path(base) / "stable-diffusion-webui" / "models" / "Stable-diffusion",
                Path(base) / "ComfyUI" / "models" / "checkpoints",
            ))
    return [path for path in candidates if path.is_dir()]


def _network_root(path: Path) -> bool:
    return str(path).startswith("\\\\")


def _drive_root(path: Path) -> bool:
    anchor = Path(path.anchor)
    return bool(path.anchor and path == anchor)
