from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable

from .errors import ConflictError, ValidationError
from .prompt_compilers import PromptCompilerRegistry


AUTHORIZATION_SCOPES = frozenset({"private", "public_evidence"})
OPERATIONS = frozenset({"txt2img", "img2img", "inpaint"})
EVIDENCE_RANK = {"declared": 0, "observed": 1, "benchmarked": 2}
REQUIREMENT_FIELDS = frozenset({
    "authorization_scope",
    "operation",
    "profile",
    "style",
    "width",
    "height",
    "affinity_tags",
    "required_vram_gb",
    "preferred_model_id",
})


class CapabilityRouter:
    def __init__(
        self,
        catalog: object,
        compilers: PromptCompilerRegistry,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = 300,
    ) -> None:
        if not isinstance(compilers, PromptCompilerRegistry):
            raise ValidationError(
                "invalid_router_compilers",
                "Capability router requires a prompt compiler registry.",
            )
        if (
            not callable(clock)
            or not isinstance(ttl_seconds, (int, float))
            or isinstance(ttl_seconds, bool)
            or ttl_seconds <= 0
        ):
            raise ValidationError(
                "invalid_router_ttl",
                "Route confirmation lifetime must be positive.",
            )
        self.catalog = catalog
        self.compilers = compilers
        self.clock = clock
        self.ttl_seconds = float(ttl_seconds)
        self._issued: dict[str, dict[str, object]] = {}

    def recommend(self, requirements: dict[str, object]) -> dict[str, object]:
        normalized = _normalize_requirements(requirements)
        available = self.catalog.list_models(normalized["authorization_scope"])
        eligible = [
            model
            for model in available
            if _hard_match(model, normalized, self.compilers)
        ]
        ranked = sorted(
            (_score_model(model, normalized) for model in eligible),
            key=lambda item: (
                -int(item["score"]),
                -EVIDENCE_RANK[str(item["evidence_level"])],
                -int(bool(item["user_pinned"])),
                str(item["model_id"]),
            ),
        )
        routes = [self._issue_route(item, normalized) for item in ranked[:3]]
        return {
            "requirements": normalized,
            "routes": routes,
            "reason": None if routes else "no_eligible_model",
        }

    def confirm(self, route_token: str, model_id: str) -> dict[str, object]:
        route = self._issued.get(route_token)
        if (
            route is None
            or route.get("model_id") != model_id
            or float(route["expires_at"]) < self.clock()
        ):
            if route is not None and float(route["expires_at"]) < self.clock():
                del self._issued[route_token]
            raise ConflictError(
                "route_confirmation_expired",
                "The displayed route changed or expired; recommend and confirm again.",
            )
        self.catalog.verify_locked_route(route)
        del self._issued[route_token]
        return copy.deepcopy(route)

    def _issue_route(
        self,
        scored: dict[str, object],
        requirements: dict[str, object],
    ) -> dict[str, object]:
        model = scored["model"]
        compiler_id = str(model["prompt_compiler_id"])
        boundary: dict[str, object] = {
            "requirements": copy.deepcopy(requirements),
            "model_id": model["id"],
            "authorization_scope": requirements["authorization_scope"],
            "operation": requirements["operation"],
            "profile": requirements["profile"],
            "style": requirements["style"],
            "width": requirements["width"],
            "height": requirements["height"],
            "backend": model["backend"],
            "endpoint_identity": model["endpoint_identity"],
            "identity_token": model["identity_token"],
            "identity_strength": model["identity_strength"],
            "sha256": model.get("sha256"),
            "hash_prefix": str(model["sha256"])[:12] if model.get("sha256") else None,
            "identity_warning": (
                None
                if model["identity_strength"] == "cryptographic"
                else "Backend binding cannot detect same-name byte replacement."
            ),
            "workflow_template_id": model.get("workflow_template_id"),
            "workflow_template_version": model.get("workflow_template_version"),
            "prompt_compiler_id": compiler_id,
            "prompt_compiler_version": self.compilers.version(compiler_id),
            "recommended_settings": copy.deepcopy(model["recommended"]),
            "limitations": copy.deepcopy(model.get("limitations", [])),
            "evidence_level": scored["evidence_level"],
            "score": scored["score"],
            "score_components": copy.deepcopy(scored["score_components"]),
            "user_pinned": scored["user_pinned"],
        }
        token = "route:" + _canonical_hash(boundary)
        route = {
            **boundary,
            "route_token": token,
            "expires_at": self.clock() + self.ttl_seconds,
        }
        self._issued[token] = copy.deepcopy(route)
        return route


def _normalize_requirements(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != REQUIREMENT_FIELDS:
        raise _invalid_requirements("Route requirement fields are incomplete or unexpected.")
    scope = value["authorization_scope"]
    operation = value["operation"]
    profile = value["profile"]
    style = value["style"]
    width = value["width"]
    height = value["height"]
    tags = value["affinity_tags"]
    vram = value["required_vram_gb"]
    preferred = value["preferred_model_id"]
    if (
        scope not in AUTHORIZATION_SCOPES
        or operation not in OPERATIONS
        or not isinstance(profile, str)
        or not profile.strip()
        or style is not None and (not isinstance(style, str) or not style.strip())
        or type(width) is not int
        or type(height) is not int
        or not 256 <= width <= 1536
        or not 256 <= height <= 1536
        or width % 8
        or height % 8
        or not isinstance(tags, list)
        or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
        or len(set(tags)) != len(tags)
        or vram is not None
        and (
            not isinstance(vram, (int, float))
            or isinstance(vram, bool)
            or vram < 0
        )
        or preferred is not None
        and (not isinstance(preferred, str) or not preferred.strip())
    ):
        raise _invalid_requirements("Route requirements contain invalid values.")
    normalized = copy.deepcopy(value)
    normalized["profile"] = profile.strip()
    normalized["style"] = style.strip() if isinstance(style, str) else None
    normalized["affinity_tags"] = sorted(tag.strip() for tag in tags)
    normalized["preferred_model_id"] = (
        preferred.strip() if isinstance(preferred, str) else None
    )
    return normalized


def _hard_match(
    model: object,
    requirements: dict[str, object],
    compilers: PromptCompilerRegistry,
) -> bool:
    if not isinstance(model, dict):
        return False
    capabilities = model.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    try:
        compilers.version(str(model["prompt_compiler_id"]))
        operations = capabilities["operations"]
        minimum = capabilities["minimum_dimension"]
        maximum = capabilities["maximum_dimension"]
        minimum_vram = capabilities["minimum_vram_gb"]
        evidence = str(model["evidence_level"])
    except (KeyError, TypeError, ValidationError):
        return False
    if evidence not in EVIDENCE_RANK:
        return False
    if (
        not isinstance(operations, list)
        or requirements["operation"] not in operations
        or type(minimum) is not int
        or type(maximum) is not int
        or not minimum <= requirements["width"] <= maximum
        or not minimum <= requirements["height"] <= maximum
    ):
        return False
    available_vram = requirements["required_vram_gb"]
    if available_vram is not None and float(minimum_vram) > float(available_vram):
        return False
    if (
        requirements["authorization_scope"] == "public_evidence"
        and model.get("identity_strength") != "cryptographic"
    ):
        return False
    if model.get("backend") == "comfyui" and not model.get("workflow_template_id"):
        return False
    return True


def _score_model(
    model: dict[str, object],
    requirements: dict[str, object],
) -> dict[str, object]:
    evidence = str(model["evidence_level"])
    affinity = set(model.get("affinity", []))
    requested_affinity = set(requirements["affinity_tags"])
    preference = model.get("preference", 0)
    preference = preference if type(preference) is int else 0
    preferred = model["id"] == requirements["preferred_model_id"]
    observed = (
        EVIDENCE_RANK[evidence] >= EVIDENCE_RANK["observed"]
        and requirements["operation"] in model.get("evidence_operations", [])
    )
    resolution = model.get("recommended", {}).get("resolution", {})
    settings_fit = (
        isinstance(resolution, dict)
        and resolution.get("width") == requirements["width"]
        and resolution.get("height") == requirements["height"]
    )
    components = {
        "preferred_model": 1000 if preferred else 0,
        "evidence": EVIDENCE_RANK[evidence] * 100,
        "observed_operation": 25 if observed else 0,
        "affinity": len(affinity & requested_affinity) * 10,
        "profile": 10 if requirements["profile"] in model.get("use_cases", []) else 0,
        "style": 10 if requirements["style"] in model.get("styles", []) else 0,
        "preference": preference,
        "settings_fit": 5 if settings_fit else 0,
    }
    return {
        "model_id": model["id"],
        "model": copy.deepcopy(model),
        "evidence_level": evidence,
        "user_pinned": preferred or preference == 100,
        "score_components": components,
        "score": sum(components.values()),
    }


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _invalid_requirements(message: str) -> ValidationError:
    return ValidationError("invalid_route_requirements", message)
