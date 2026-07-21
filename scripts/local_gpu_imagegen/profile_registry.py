from __future__ import annotations

import copy
import json
from pathlib import Path

from .errors import ValidationError


PROFILE_REQUIRED = {
    "schema_version", "id", "kind", "description", "aliases", "examples", "subtypes",
    "defaults", "prompt_guidance", "prohibited_content", "rubric", "hard_failures",
    "refine_mutable", "explore_mutable",
}
STYLE_REQUIRED = {
    "schema_version", "id", "kind", "description", "aliases", "prompt_guidance",
    "negative_guidance", "rubric", "hard_failures", "known_failure_patterns", "model_hints",
}
MODEL_REQUIRED = {
    "schema_version", "id", "kind", "source", "license_id", "license_url",
    "license_status", "backends", "local_discovery_names", "strengths", "limitations",
    "use_cases", "styles", "recommended", "known_local", "enabled",
}
BASE_CRITICAL_RUBRIC = frozenset({"intent_adherence", "composition", "artifact_control"})
PROFILE_CRITICAL_RUBRIC = {
    "standalone-illustration": frozenset({
        "subject_completeness",
        "face_quality",
        "hand_quality",
        "style_consistency",
        "detail_quality",
    }),
    "presentation-visual": frozenset({
        "aspect_ratio",
        "safe_area",
        "theme_consistency",
        "visual_hierarchy",
        "overlay_contrast",
        "crop_safety",
    }),
    "ui-visual-asset": frozenset({
        "dimensions",
        "aspect_ratio",
        "crop_tolerance",
        "palette_compatibility",
        "style_system_consistency",
        "layout_composability",
        "edge_quality",
    }),
}


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("invalid_profile_json", f"Cannot load profile JSON: {path.name}", {"path": str(path)}) from exc
    if not isinstance(value, dict):
        raise ValidationError("invalid_profile_document", f"Profile document must be an object: {path.name}")
    return value


def _validate(document: dict[str, object], required: set[str], expected_kind: str) -> None:
    missing = sorted(required - set(document))
    if missing:
        raise ValidationError("missing_profile_fields", f"Missing fields: {', '.join(missing)}", {"fields": missing})
    if document["kind"] != expected_kind:
        raise ValidationError("invalid_profile_kind", f"Expected kind {expected_kind}.")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValidationError("unsupported_profile_schema", "Only schema_version 1 is supported.")


def _validate_model_approval(document: dict[str, object]) -> None:
    if type(document["enabled"]) is not bool or type(document["known_local"]) is not bool:
        raise ValidationError("invalid_profile_document", "Model enabled and known_local must be booleans.")
    license_status = document["license_status"]
    if not isinstance(license_status, str) or license_status not in {
        "approved", "requires_user_review", "rejected",
    }:
        raise ValidationError("invalid_profile_document", "Model license_status is invalid.")


def _validate_profile_shape(document: dict[str, object]) -> None:
    for field in (
        "aliases",
        "subtypes",
        "prohibited_content",
        "hard_failures",
        "refine_mutable",
        "explore_mutable",
    ):
        value = document.get(field)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValidationError(
                "invalid_profile_document",
                f"{field} must be a non-empty list of non-empty strings.",
            )

    subtypes = document["subtypes"]
    examples = document.get("examples")
    if not isinstance(examples, dict) or set(examples) != set(subtypes):
        raise ValidationError(
            "invalid_profile_document",
            "examples must contain exactly one entry for every subtype.",
        )
    for subtype, values in examples.items():
        if not isinstance(values, list) or not values or not all(
            isinstance(item, str) and item.strip() for item in values
        ):
            raise ValidationError(
                "invalid_profile_document",
                f"examples.{subtype} must be a non-empty list of non-empty strings.",
            )

    rubric = document.get("rubric")
    if not isinstance(rubric, dict) or not rubric:
        raise ValidationError("invalid_profile_document", "rubric must be a non-empty object.")
    for name, specification in rubric.items():
        if not isinstance(name, str) or not name or not isinstance(specification, dict):
            raise ValidationError("invalid_profile_document", "rubric entries must be objects.")
        weight = specification.get("weight")
        critical = specification.get("critical")
        if type(weight) is not int or weight < 1:
            raise ValidationError(
                "invalid_profile_document",
                f"rubric.{name}.weight must be an integer of at least 1.",
            )
        if type(critical) is not bool:
            raise ValidationError(
                "invalid_profile_document",
                f"rubric.{name}.critical must be a boolean.",
            )


class ProfileRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._models = self._documents(self.root / "models", MODEL_REQUIRED, "model")

    def list_catalog(self) -> dict[str, dict[str, dict[str, object]]]:
        self._validated_base()
        profiles = self._documents(self.root / "use-cases", PROFILE_REQUIRED, "use_case")
        styles = self._documents(self.root / "styles", STYLE_REQUIRED, "style")
        return {
            "profiles": {identifier: self._catalog_entry(document) for identifier, document in profiles.items()},
            "styles": {identifier: self._catalog_entry(document) for identifier, document in styles.items()},
            "models": {identifier: self._catalog_entry(document) for identifier, document in self._models.items()},
        }

    def merge(self, profile_id: str, style_id: str | None, constraints: dict[str, object]) -> dict[str, object]:
        if not isinstance(constraints, dict):
            raise ValidationError("invalid_constraints", "Constraints must be an object.")

        base = self._validated_base()
        profile = self._documents(self.root / "use-cases", PROFILE_REQUIRED, "use_case").get(profile_id)
        if profile is None:
            raise ValidationError("unknown_profile", f"Unknown profile: {profile_id}", {"profile": profile_id})

        style: dict[str, object] | None = None
        if style_id is not None:
            style = self._documents(self.root / "styles", STYLE_REQUIRED, "style").get(style_id)
            if style is None:
                raise ValidationError("unknown_style", f"Unknown style: {style_id}", {"style": style_id})

        merged_constraints: dict[str, object] = {}
        merged_constraints.update(self._object(base, "defaults"))
        if style is not None:
            merged_constraints.update(self._object(style, "defaults"))
        merged_constraints.update(self._object(profile, "defaults"))
        merged_constraints.update(constraints)
        max_rounds = merged_constraints.get("max_rounds")
        if type(max_rounds) is not int or not 1 <= max_rounds <= 3:
            raise ValidationError("invalid_round_budget", "max_rounds must be an integer from 1 to 3.")

        rubric: dict[str, object] = {}
        rubric.update(self._object(base, "rubric"))
        if style is not None:
            rubric.update(self._object(style, "rubric"))
        rubric.update(self._object(profile, "rubric"))
        self._require_critical_dimensions(
            rubric,
            BASE_CRITICAL_RUBRIC | PROFILE_CRITICAL_RUBRIC.get(profile_id, frozenset()),
            profile_id,
        )
        hard_failures: list[str] = []
        for document in (style, profile):
            if document is None:
                continue
            for failure in document["hard_failures"]:
                if failure not in hard_failures:
                    hard_failures.append(failure)
        return {
            "profile": copy.deepcopy(profile),
            "style": copy.deepcopy(style),
            "constraints": copy.deepcopy(merged_constraints),
            "rubric": copy.deepcopy(rubric),
            "hard_failures": hard_failures,
            "refine_mutable": copy.deepcopy(profile["refine_mutable"]),
            "explore_mutable": copy.deepcopy(profile["explore_mutable"]),
        }

    def validate_model_choice(self, model_id: str) -> dict[str, object]:
        model = self._models.get(model_id)
        if model is None:
            raise ValidationError("unknown_model", f"Unknown model: {model_id}")
        if not model["enabled"]:
            raise ValidationError("model_not_enabled", f"Model is not approved for generation: {model_id}")
        if model["license_status"] != "approved":
            raise ValidationError("model_license_unapproved", f"Model license is not approved: {model_id}")
        return copy.deepcopy(model)

    @staticmethod
    def _catalog_entry(document: dict[str, object]) -> dict[str, object]:
        return copy.deepcopy(document)

    @staticmethod
    def _object(document: dict[str, object], field: str) -> dict[str, object]:
        value = document.get(field, {})
        if not isinstance(value, dict):
            raise ValidationError("invalid_profile_document", f"{field} must be an object.")
        return value

    def _validated_base(self) -> dict[str, object]:
        base = _load_json(self.root / "base.json")
        self._require_critical_dimensions(self._object(base, "rubric"), BASE_CRITICAL_RUBRIC, "base")
        return base

    @staticmethod
    def _require_critical_dimensions(
        rubric: dict[str, object],
        dimensions: frozenset[str],
        profile_id: str,
    ) -> None:
        missing = sorted(
            name
            for name in dimensions
            if not isinstance(rubric.get(name), dict) or rubric[name].get("critical") is not True
        )
        if missing:
            raise ValidationError(
                "missing_critical_rubric_dimension",
                f"Required critical rubric dimensions are missing: {', '.join(missing)}.",
                {"profile": profile_id, "dimensions": missing},
            )

    @staticmethod
    def _documents(directory: Path, required: set[str], kind: str) -> dict[str, dict[str, object]]:
        if not directory.exists():
            return {}
        documents: dict[str, dict[str, object]] = {}
        for path in sorted(directory.glob("*.json")):
            document = _load_json(path)
            _validate(document, required, kind)
            identifier = document["id"]
            if not isinstance(identifier, str) or not identifier:
                raise ValidationError("invalid_profile_document", f"Profile id must be a non-empty string: {path.name}")
            if kind == "model":
                _validate_model_approval(document)
            required_critical = PROFILE_CRITICAL_RUBRIC.get(identifier)
            if required_critical is not None:
                ProfileRegistry._require_critical_dimensions(
                    ProfileRegistry._object(document, "rubric"),
                    required_critical,
                    identifier,
                )
            if kind == "use_case":
                _validate_profile_shape(document)
            if identifier in documents:
                raise ValidationError("duplicate_profile_id", f"Duplicate profile id: {identifier}")
            documents[identifier] = document
        return documents
