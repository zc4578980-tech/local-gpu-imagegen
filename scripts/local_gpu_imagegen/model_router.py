from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable

from .errors import AssetEngineError, ConflictError, ValidationError
from .prompt_compilers import PromptCompilerRegistry
from .regional_layout import (
    REGIONAL_TEMPLATE_ID,
    validate_regional_layout,
)
from .two_stage_layout import (
    TWO_STAGE_TEMPLATE_ID,
    build_control_identity,
    validate_two_stage_layout,
)


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
OPTIONAL_REQUIREMENT_FIELDS = frozenset({"regional_layout", "two_stage_layout"})
LAYOUT_REQUIREMENTS = {
    "regional_layout": {
        "capability_field": "regional_layout_modes",
        "template_id": REGIONAL_TEMPLATE_ID,
        "unavailable_reason": "regional_layout_unavailable",
    },
    "two_stage_layout": {
        "capability_field": "two_stage_layout_modes",
        "template_id": TWO_STAGE_TEMPLATE_ID,
        "unavailable_reason": "two_stage_layout_unavailable",
    },
}


class CapabilityRouter:
    def __init__(
        self,
        catalog: object,
        compilers: PromptCompilerRegistry,
        *,
        layout_capability_provider: Callable[[str], dict[str, object]] | None = None,
        regional_capability_provider: Callable[[str], dict[str, object]] | None = None,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = 300,
    ) -> None:
        if not isinstance(compilers, PromptCompilerRegistry):
            raise ValidationError(
                "invalid_router_compilers",
                "Capability router requires a prompt compiler registry.",
            )
        if (
            (
                layout_capability_provider is not None
                and not callable(layout_capability_provider)
            )
            or (
                regional_capability_provider is not None
                and not callable(regional_capability_provider)
            )
            or (
                layout_capability_provider is not None
                and regional_capability_provider is not None
                and layout_capability_provider is not regional_capability_provider
            )
            or not callable(clock)
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
        provider = (
            layout_capability_provider
            if layout_capability_provider is not None
            else regional_capability_provider
        )
        self.layout_capability_provider = provider
        self.regional_capability_provider = provider
        self.clock = clock
        self.ttl_seconds = float(ttl_seconds)
        self._issued: dict[str, dict[str, object]] = {}

    def recommend(self, requirements: dict[str, object]) -> dict[str, object]:
        normalized = _normalize_requirements(requirements)
        layout_key = next(
            (key for key in LAYOUT_REQUIREMENTS if key in normalized),
            None,
        )
        layout_capability = None
        if layout_key is not None:
            layout = normalized[layout_key]
            assert isinstance(layout, dict)
            layout_capability = self._layout_capability(
                str(layout["mode"])
            )
            if layout_capability["available"] is not True:
                return {
                    "requirements": normalized,
                    "routes": [],
                    "reason": LAYOUT_REQUIREMENTS[layout_key]["unavailable_reason"],
                    "next_action": "display_and_wait",
                }
        available = self.catalog.list_models(normalized["authorization_scope"])
        preferred_model_id = normalized["preferred_model_id"]
        preferred_available = None
        if preferred_model_id is not None:
            preferred_available = next(
                (
                    model
                    for model in available
                    if isinstance(model, dict)
                    and model.get("id") == preferred_model_id
                ),
                None,
            )
            if preferred_available is None:
                raise ValidationError(
                    "preferred_model_not_found",
                    "preferred_model_id must exactly match a current catalog model ID.",
                    {"preferred_model_id": preferred_model_id},
                )
        eligible = [
            model
            for model in available
            if _hard_match(
                model,
                normalized,
                self.compilers,
                layout_capability,
            )
        ]
        if (
            preferred_model_id is not None
            and not any(
                isinstance(model, dict)
                and model.get("id") == preferred_model_id
                for model in eligible
            )
        ):
            raise ValidationError(
                "preferred_model_ineligible",
                "The preferred catalog model does not satisfy the requested route boundary.",
                {"preferred_model_id": preferred_model_id},
            )
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
            "next_action": "display_and_wait",
        }

    def _layout_capability(self, mode: str) -> dict[str, object]:
        provider = self.layout_capability_provider
        if provider is None:
            return {
                "mode": mode,
                "available": False,
                "endpoint_identity": None,
                "reason": "regional_layout_unavailable",
            }
        try:
            result = provider(mode)
        except AssetEngineError as error:
            return {
                "mode": mode,
                "available": False,
                "endpoint_identity": None,
                "reason": error.code,
            }
        endpoint = result.get("endpoint_identity") if isinstance(result, dict) else None
        reason = result.get("reason") if isinstance(result, dict) else None
        available = result.get("available") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or set(result)
            != {"mode", "available", "endpoint_identity", "reason"}
            or result.get("mode") != mode
            or type(available) is not bool
            or (endpoint is not None and not isinstance(endpoint, str))
            or (reason is not None and not isinstance(reason, str))
            or (
                available is True
                and (
                    not isinstance(endpoint, str)
                    or not endpoint
                    or reason is not None
                )
            )
        ):
            return {
                "mode": mode,
                "available": False,
                "endpoint_identity": None,
                "reason": "regional_layout_unavailable",
            }
        return copy.deepcopy(result)

    def validate_confirmation(
        self,
        route_token: str,
        model_id: str,
    ) -> dict[str, object]:
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
        return copy.deepcopy(route)

    def confirm(self, route_token: str, model_id: str) -> dict[str, object]:
        route = self.validate_confirmation(route_token, model_id)
        del self._issued[route_token]
        return route

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
            "component_bundle": copy.deepcopy(model.get("component_bundle")),
            "component_bundle_sha256": model.get("component_bundle_sha256"),
            "prompt_compiler_id": compiler_id,
            "prompt_compiler_version": self.compilers.version(compiler_id),
            "recommended_settings": copy.deepcopy(model["recommended"]),
            "limitations": copy.deepcopy(model.get("limitations", [])),
            "evidence_level": scored["evidence_level"],
            "score": scored["score"],
            "score_components": copy.deepcopy(scored["score_components"]),
            "user_pinned": scored["user_pinned"],
        }
        if model.get("workflow_template_id") == TWO_STAGE_TEMPLATE_ID:
            boundary["control_sha256"] = model.get("control_sha256")
        token = "route:" + _canonical_hash(boundary)
        route = {
            **boundary,
            "route_token": token,
            "expires_at": self.clock() + self.ttl_seconds,
        }
        route["start_run_boundary"] = {
            "profile": route["profile"],
            "style": route["style"],
            "constraints": {
                "width": route["width"],
                "height": route["height"],
            },
            "model_choice": route["model_id"],
            "backend": route["backend"],
            "authorization_scope": route["authorization_scope"],
            "route_token": route["route_token"],
        }
        self._issued[token] = copy.deepcopy(route)
        return route


def _normalize_requirements(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or not REQUIREMENT_FIELDS <= set(value)
        or set(value) - REQUIREMENT_FIELDS
        not in (set(), {"regional_layout"}, {"two_stage_layout"})
    ):
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
    if "regional_layout" in value:
        normalized["regional_layout"] = validate_regional_layout(
            value["regional_layout"]
        )
    if "two_stage_layout" in value:
        normalized["two_stage_layout"] = validate_two_stage_layout(
            value["two_stage_layout"]
        )
    return normalized


def _hard_match(
    model: object,
    requirements: dict[str, object],
    compilers: PromptCompilerRegistry,
    layout_capability: dict[str, object] | None,
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
    if (
        requirements["authorization_scope"] == "public_evidence"
        and model.get("backend") == "comfyui"
        and (
            not isinstance(model.get("component_bundle"), dict)
            or not isinstance(model.get("component_bundle_sha256"), str)
        )
    ):
        return False
    if model.get("backend") == "comfyui" and not model.get("workflow_template_id"):
        return False
    layout_key = next(
        (key for key in LAYOUT_REQUIREMENTS if key in requirements),
        None,
    )
    if layout_key is not None:
        layout = requirements[layout_key]
        assert isinstance(layout, dict)
        specification = LAYOUT_REQUIREMENTS[layout_key]
        modes = capabilities.get(specification["capability_field"])
        if (
            layout_capability is None
            or layout_capability.get("available") is not True
            or model.get("backend") != "comfyui"
            or model.get("endpoint_identity")
            != layout_capability.get("endpoint_identity")
            or model.get("workflow_template_id") != specification["template_id"]
            or not isinstance(modes, list)
            or layout["mode"] not in modes
        ):
            return False
        if layout_key == "two_stage_layout" and not _two_stage_identity_matches(
            model,
            layout,
        ):
            return False
    elif model.get("workflow_template_id") in {
        REGIONAL_TEMPLATE_ID,
        TWO_STAGE_TEMPLATE_ID,
    }:
        return False
    return True


def _two_stage_identity_matches(
    model: dict[str, object],
    layout: dict[str, object],
) -> bool:
    bundle = model.get("component_bundle")
    bundle_sha256 = model.get("component_bundle_sha256")
    workflow = bundle.get("workflow") if isinstance(bundle, dict) else None
    if (
        not isinstance(bundle, dict)
        or not isinstance(bundle_sha256, str)
        or bundle.get("bundle_sha256") != bundle_sha256
        or not isinstance(workflow, dict)
        or workflow.get("template_id") != TWO_STAGE_TEMPLATE_ID
        or workflow.get("template_version") != model.get("workflow_template_version")
        or not isinstance(workflow.get("sha256"), str)
    ):
        return False
    try:
        expected_control = build_control_identity(
            layout,
            workflow["sha256"],
            "base-subject-v1",
        )
    except AssetEngineError:
        return False
    return model.get("control_sha256") == expected_control


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
