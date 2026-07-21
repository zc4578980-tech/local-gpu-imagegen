from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from pathlib import Path

from .errors import AssetEngineError, ConflictError, ValidationError
from .model_identity import identity_token, validate_discovery_record
from .prompt_compilers import COMPILER_VERSIONS


AUTHORIZATION_SCOPES = frozenset({"private", "public_evidence"})
OPERATIONS = frozenset({"txt2img", "img2img", "inpaint"})
EVIDENCE_LEVELS = frozenset({"declared", "observed", "benchmarked"})
REPOSITORY_REQUIRED = frozenset({
    "schema_version",
    "id",
    "kind",
    "source",
    "license_id",
    "license_url",
    "license_status",
    "backends",
    "local_discovery_names",
    "strengths",
    "limitations",
    "use_cases",
    "styles",
    "recommended",
    "known_local",
    "enabled",
    "model_family",
    "prompt_dialect",
    "capabilities",
    "affinity",
    "evidence",
})
LOCKED_ROUTE_FIELDS = (
    "identity_token",
    "identity_strength",
    "backend",
    "endpoint_identity",
    "workflow_template_id",
    "workflow_template_version",
)


class ModelCatalog:
    def __init__(
        self,
        repository_root: Path,
        inventory_provider: Callable[[], list[dict[str, object]]],
        trust_registry: object,
        readiness_provider: Callable[[], dict[str, object]],
        workflows: object,
    ) -> None:
        if not callable(inventory_provider) or not callable(readiness_provider):
            raise ValidationError(
                "invalid_model_catalog",
                "Model catalog providers must be callable.",
            )
        self.repository_root = Path(repository_root)
        self.inventory_provider = inventory_provider
        self.trust_registry = trust_registry
        self.readiness_provider = readiness_provider
        self.workflows = workflows

    def list_models(self, scope: str) -> list[dict[str, object]]:
        if scope not in AUTHORIZATION_SCOPES:
            raise ValidationError(
                "invalid_authorization_scope",
                "Authorization scope must be private or public_evidence.",
            )
        inventory = self._inventory()
        ready = self._ready_backends()
        records = self._repository_records(inventory, ready)
        records.extend(self._local_records(inventory, ready))
        eligible = [
            record
            for record in records
            if scope == "private" or _public_eligible(record)
        ]
        eligible.sort(key=lambda record: str(record["id"]))
        return copy.deepcopy(eligible)

    def resolve(self, model_id: str, scope: str) -> dict[str, object]:
        if not isinstance(model_id, str) or not model_id:
            raise ValidationError("model_not_eligible", "Model ID must be non-empty.")
        matches = [
            model for model in self.list_models(scope) if model["id"] == model_id
        ]
        if len(matches) != 1:
            raise ValidationError(
                "model_not_eligible",
                "Model is not currently eligible for the requested scope.",
                {"model_id": model_id, "scope": scope},
            )
        return matches[0]

    def verify_locked_route(self, route: dict[str, object]) -> dict[str, object]:
        if not isinstance(route, dict):
            raise ConflictError(
                "model_identity_drifted",
                "Confirmed model route is invalid.",
            )
        try:
            current = self.resolve(
                str(route["model_id"]),
                str(route["authorization_scope"]),
            )
        except (KeyError, ValidationError) as error:
            raise ConflictError(
                "model_identity_drifted",
                "Confirmed model is no longer eligible.",
            ) from error
        for field in LOCKED_ROUTE_FIELDS:
            if current.get(field) != route.get(field):
                raise ConflictError(
                    "model_identity_drifted",
                    "Confirmed model, endpoint, or workflow changed before generation.",
                    {"field": field},
                )
        return current

    def record_observation(
        self,
        model_id: str,
        identity: str,
        operation: str,
        run_id: str,
    ) -> None:
        if not model_id.startswith("local:"):
            return
        current = self.resolve(model_id, "private")
        if current["identity_token"] != identity:
            raise ConflictError(
                "model_identity_drifted",
                "Cannot record an observation for a changed identity.",
            )
        self.trust_registry.record_observation(
            model_id,
            str(current.get("trust_identity_token", identity)),
            operation,
            run_id,
        )

    def _inventory(self) -> dict[str, dict[str, object]]:
        value = self.inventory_provider()
        if not isinstance(value, list):
            raise ValidationError(
                "invalid_model_inventory",
                "Discovery inventory must be an array.",
            )
        inventory: dict[str, dict[str, object]] = {}
        for item in value:
            if (
                isinstance(item, dict)
                and item.get("source_type") == "filesystem"
                and item.get("identity_strength") is None
            ):
                continue
            validated = validate_discovery_record(item)
            token = identity_token(validated)
            validated["identity_token"] = token
            if token in inventory:
                raise ValidationError(
                    "invalid_model_inventory",
                    "Discovery inventory contains duplicate identities.",
                )
            inventory[token] = validated
        return inventory

    def _ready_backends(self) -> set[str]:
        value = self.readiness_provider()
        if not isinstance(value, dict):
            raise ValidationError(
                "invalid_capabilities",
                "Backend readiness provider must return an object.",
            )
        advertised = value.get("available_backends")
        if advertised is None:
            advertised = [
                backend
                for backend in ("webui", "comfyui", "diffusers")
                if value.get(f"{backend}_ready") is True
            ]
        if not isinstance(advertised, list) or any(
            not isinstance(item, str) or not item for item in advertised
        ):
            raise ValidationError(
                "invalid_capabilities",
                "Backend readiness must advertise backend IDs.",
            )
        return set(advertised)

    def _repository_records(
        self,
        inventory: dict[str, dict[str, object]],
        ready: set[str],
    ) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        values = sorted(inventory.values(), key=lambda item: str(item["identity_token"]))
        for template in self._repository_models():
            if (
                template["enabled"] is not True
                or template["known_local"] is not True
                or template["license_status"] != "approved"
            ):
                continue
            candidates = [
                item
                for item in values
                if item["backend"] in template["backends"]
                and item["backend"] in ready
                and _repository_identity_match(template, item)
            ]
            if not candidates:
                continue
            current = candidates[0]
            records.append({
                **copy.deepcopy(template),
                **_identity_fields(current),
                "prompt_compiler_id": template["prompt_dialect"],
                "evidence_level": template["evidence"]["level"],
                "evidence_operations": copy.deepcopy(
                    template["evidence"]["operations"]
                ),
                "preference": 0,
                "workflow_template_id": None,
                "workflow_template_version": None,
                "public_candidate": (
                    template.get("output_redistribution_status") == "approved"
                ),
            })
        return records

    def _local_records(
        self,
        inventory: dict[str, dict[str, object]],
        ready: set[str],
    ) -> list[dict[str, object]]:
        records = self.trust_registry.list_records()
        if not isinstance(records, list):
            raise ValidationError(
                "invalid_trust_record",
                "Trust registry must return an array.",
            )
        merged: list[dict[str, object]] = []
        for trust in records:
            if not isinstance(trust, dict):
                raise ValidationError(
                    "invalid_trust_record",
                    "Trust records must be objects.",
                )
            token = trust.get("identity_token")
            current = inventory.get(token) if isinstance(token, str) else None
            if current is None:
                continue
            capabilities = _normalize_local_capabilities(trust.get("capabilities"))
            execution = _execution_identity(current, trust, inventory)
            if execution is None:
                continue
            backend = str(execution["backend"])
            if backend not in ready:
                continue
            workflow_id, workflow_version = self._workflow_fields(
                backend,
                execution,
                trust,
                capabilities,
            )
            if backend == "comfyui" and workflow_id is None:
                continue
            evidence_level, evidence_operations = _trust_evidence(trust.get("evidence"))
            merged.append({
                "id": trust.get("catalog_id"),
                "kind": "model",
                "source": "local-trust-registry",
                **_identity_fields(execution),
                "trust_identity_token": token,
                "model_family": capabilities["model_family"],
                "prompt_dialect": capabilities["prompt_dialect"],
                "prompt_compiler_id": capabilities["prompt_dialect"],
                "capabilities": capabilities["capabilities"],
                "affinity": capabilities["affinity"],
                "evidence_level": evidence_level,
                "evidence_operations": evidence_operations,
                "preference": trust.get("preference", 0),
                "limitations": copy.deepcopy(trust.get("limitations", [])),
                "recommended": capabilities["recommended"],
                "use_cases": [],
                "styles": [],
                "workflow_template_id": workflow_id,
                "workflow_template_version": workflow_version,
                "trust_scope": trust.get("scope"),
                "public_metadata": copy.deepcopy(trust.get("public_metadata")),
                "public_candidate": trust.get("scope") == "public_candidate",
            })
        return merged

    def _workflow_fields(
        self,
        backend: str,
        current: dict[str, object],
        trust: dict[str, object],
        capabilities: dict[str, object],
    ) -> tuple[str | None, int | None]:
        if backend != "comfyui":
            return None, None
        binding = trust.get("workflow_binding")
        if not isinstance(binding, dict):
            return None, None
        template_id = binding.get("template_id")
        version = binding.get("template_version")
        if not isinstance(template_id, str) or type(version) is not int or version < 1:
            return None, None
        operation = capabilities["capabilities"]["operations"][0]
        recommended = capabilities["recommended"]
        try:
            resolved = self.workflows.resolve(
                template_id,
                str(current["backend_model_id"]),
                operation,
                {
                    "positive_prompt": "catalog validation",
                    "negative_prompt": "",
                    "seed": 0,
                    "steps": recommended["steps"],
                    "guidance_scale": recommended["guidance"],
                    "sampler": recommended["sampler"] or "euler",
                    "scheduler": recommended["scheduler"] or "normal",
                    "width": recommended["resolution"]["width"],
                    "height": recommended["resolution"]["height"],
                },
            )
        except (AttributeError, AssetEngineError):
            return None, None
        if resolved.get("template_version") != version:
            return None, None
        return template_id, version

    def _repository_models(self) -> list[dict[str, object]]:
        if not self.repository_root.exists():
            return []
        values = []
        for path in sorted(self.repository_root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValidationError(
                    "invalid_model_template",
                    "Repository model template is unreadable.",
                    {"file": path.name},
                ) from error
            values.append(_validate_repository_model(value))
        return values


def _validate_repository_model(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or REPOSITORY_REQUIRED - set(value):
        raise ValidationError(
            "invalid_model_template",
            "Repository model template fields are incomplete.",
        )
    if (
        value["schema_version"] != 1
        or value["kind"] != "model"
        or not isinstance(value["id"], str)
        or not value["id"]
        or type(value["enabled"]) is not bool
        or type(value["known_local"]) is not bool
        or not isinstance(value["backends"], list)
        or not isinstance(value["local_discovery_names"], list)
        or not isinstance(value["model_family"], str)
        or value["prompt_dialect"] not in COMPILER_VERSIONS
        or not _string_list(value["affinity"])
    ):
        raise ValidationError(
            "invalid_model_template",
            "Repository model template metadata is invalid.",
        )
    capabilities = _validate_capabilities(value["capabilities"])
    evidence = value["evidence"]
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"level", "operations"}
        or evidence.get("level") not in EVIDENCE_LEVELS
        or not _operations(evidence.get("operations"))
    ):
        raise ValidationError(
            "invalid_model_template",
            "Repository model evidence is invalid.",
        )
    recommended = _validate_recommended(value["recommended"])
    result = copy.deepcopy(value)
    result["capabilities"] = capabilities
    result["recommended"] = recommended
    return result


def _normalize_local_capabilities(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError(
            "invalid_model_capabilities",
            "Trusted model capabilities must be an object.",
        )
    required = {
        "model_family",
        "prompt_dialect",
        "operations",
        "minimum_dimension",
        "maximum_dimension",
        "minimum_vram_gb",
        "negative_prompt",
        "affinity",
        "recommended",
    }
    if set(value) != required or value["prompt_dialect"] not in COMPILER_VERSIONS:
        raise ValidationError(
            "invalid_model_capabilities",
            "Trusted model capability fields are invalid.",
        )
    capabilities = _validate_capabilities({
        key: value[key]
        for key in (
            "operations",
            "minimum_dimension",
            "maximum_dimension",
            "minimum_vram_gb",
            "negative_prompt",
        )
    })
    if not isinstance(value["model_family"], str) or not value["model_family"].strip():
        raise ValidationError("invalid_model_capabilities", "Model family is invalid.")
    if not _string_list(value["affinity"]):
        raise ValidationError("invalid_model_capabilities", "Model affinity is invalid.")
    return {
        "model_family": value["model_family"],
        "prompt_dialect": value["prompt_dialect"],
        "capabilities": capabilities,
        "affinity": copy.deepcopy(value["affinity"]),
        "recommended": _validate_recommended(value["recommended"]),
    }


def _validate_capabilities(value: object) -> dict[str, object]:
    fields = {
        "operations",
        "minimum_dimension",
        "maximum_dimension",
        "minimum_vram_gb",
        "negative_prompt",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(
            "invalid_model_capabilities",
            "Model capability fields are invalid.",
        )
    minimum = value["minimum_dimension"]
    maximum = value["maximum_dimension"]
    vram = value["minimum_vram_gb"]
    if (
        not _operations(value["operations"])
        or type(minimum) is not int
        or type(maximum) is not int
        or not 256 <= minimum <= maximum <= 1536
        or not isinstance(vram, (int, float))
        or isinstance(vram, bool)
        or vram < 0
        or value["negative_prompt"] not in {"supported", "ignored", "unsupported"}
    ):
        raise ValidationError(
            "invalid_model_capabilities",
            "Model capabilities are outside supported limits.",
        )
    return copy.deepcopy(value)


def _validate_recommended(value: object) -> dict[str, object]:
    fields = {"resolution", "steps", "guidance", "sampler", "scheduler"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(
            "invalid_model_settings",
            "Recommended model settings are invalid.",
        )
    resolution = value["resolution"]
    if (
        not isinstance(resolution, dict)
        or set(resolution) != {"width", "height"}
        or any(type(resolution[key]) is not int for key in ("width", "height"))
        or any(
            not 256 <= resolution[key] <= 1536 or resolution[key] % 8
            for key in ("width", "height")
        )
        or type(value["steps"]) is not int
        or not 1 <= value["steps"] <= 80
        or not isinstance(value["guidance"], (int, float))
        or isinstance(value["guidance"], bool)
        or not math.isfinite(float(value["guidance"]))
        or value["guidance"] < 0
        or value["sampler"] is not None and not isinstance(value["sampler"], str)
        or value["scheduler"] is not None and not isinstance(value["scheduler"], str)
    ):
        raise ValidationError(
            "invalid_model_settings",
            "Recommended model settings are outside supported limits.",
        )
    return copy.deepcopy(value)


def _repository_identity_match(
    template: dict[str, object],
    current: dict[str, object],
) -> bool:
    expected_hash = template.get("sha256")
    if isinstance(expected_hash, str):
        return current["sha256"] == expected_hash
    return current["backend_model_id"] in template["local_discovery_names"]


def _execution_identity(
    current: dict[str, object],
    trust: dict[str, object],
    inventory: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    if current["backend"] != "filesystem":
        return copy.deepcopy(current)
    binding = trust.get("workflow_binding")
    if not isinstance(binding, dict):
        return None
    backend = binding.get("backend")
    model_id = binding.get("backend_model_id")
    endpoint = binding.get("endpoint_identity")
    if not isinstance(backend, str) or not isinstance(model_id, str):
        return None
    candidates = [
        item
        for item in inventory.values()
        if item["backend"] == backend
        and item["backend_model_id"] == model_id
        and (endpoint is None or item["endpoint_identity"] == endpoint)
    ]
    if len(candidates) != 1:
        return None
    backend_record = candidates[0]
    if backend == "webui":
        return copy.deepcopy(backend_record)
    derived = validate_discovery_record({
        "backend": backend,
        "endpoint_identity": backend_record["endpoint_identity"],
        "backend_model_id": backend_record["backend_model_id"],
        "format": current["format"],
        "byte_size": current["byte_size"],
        "modified_ns": current["modified_ns"],
        "sha256": current["sha256"],
        "identity_strength": current["identity_strength"],
        "metadata": copy.deepcopy(backend_record["metadata"]),
    })
    derived["identity_token"] = identity_token(derived)
    return derived


def _identity_fields(value: dict[str, object]) -> dict[str, object]:
    return {
        field: copy.deepcopy(value[field])
        for field in (
            "backend",
            "endpoint_identity",
            "backend_model_id",
            "format",
            "byte_size",
            "modified_ns",
            "sha256",
            "identity_strength",
            "metadata",
            "identity_token",
            "public_evidence_eligible",
        )
    }


def _trust_evidence(value: object) -> tuple[str, list[str]]:
    if not isinstance(value, list) or not value or value[0] != {"level": "declared"}:
        raise ValidationError("invalid_trust_record", "Trust evidence is invalid.")
    operations = []
    for item in value[1:]:
        if (
            not isinstance(item, dict)
            or item.get("level") != "observed"
            or item.get("operation") not in OPERATIONS
        ):
            raise ValidationError("invalid_trust_record", "Trust evidence is invalid.")
        if item["operation"] not in operations:
            operations.append(item["operation"])
    return ("observed" if operations else "declared"), operations


def _public_eligible(record: dict[str, object]) -> bool:
    if record.get("identity_strength") != "cryptographic":
        return False
    if record.get("source") == "local-trust-registry":
        metadata = record.get("public_metadata")
        return (
            record.get("trust_scope") == "public_candidate"
            and isinstance(metadata, dict)
            and metadata.get("output_redistribution_status") == "approved"
        )
    return (
        record.get("license_status") == "approved"
        and record.get("public_candidate") is True
    )


def _operations(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(item in OPERATIONS for item in value)
        and len(set(value)) == len(value)
    )


def _string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item.strip() for item in value)
        and len(set(value)) == len(value)
    )
