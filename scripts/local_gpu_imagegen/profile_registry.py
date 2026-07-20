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
    if document["schema_version"] != 1:
        raise ValidationError("unsupported_profile_schema", "Only schema_version 1 is supported.")


class ProfileRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_catalog(self) -> dict[str, dict[str, dict[str, object]]]:
        profiles = self._documents(self.root / "use-cases", PROFILE_REQUIRED, "use_case")
        styles = self._documents(self.root / "styles", STYLE_REQUIRED, "style")
        return {
            "profiles": {identifier: self._catalog_entry(document) for identifier, document in profiles.items()},
            "styles": {identifier: self._catalog_entry(document) for identifier, document in styles.items()},
        }

    def merge(self, profile_id: str, style_id: str | None, constraints: dict[str, object]) -> dict[str, object]:
        if not isinstance(constraints, dict):
            raise ValidationError("invalid_constraints", "Constraints must be an object.")

        base = _load_json(self.root / "base.json")
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
        return {
            "profile": copy.deepcopy(profile),
            "style": copy.deepcopy(style),
            "constraints": copy.deepcopy(merged_constraints),
            "rubric": copy.deepcopy(rubric),
        }

    @staticmethod
    def _catalog_entry(document: dict[str, object]) -> dict[str, object]:
        return {
            "description": document["description"],
            "aliases": copy.deepcopy(document["aliases"]),
        }

    @staticmethod
    def _object(document: dict[str, object], field: str) -> dict[str, object]:
        value = document.get(field, {})
        if not isinstance(value, dict):
            raise ValidationError("invalid_profile_document", f"{field} must be an object.")
        return value

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
            if identifier in documents:
                raise ValidationError("duplicate_profile_id", f"Duplicate profile id: {identifier}")
            documents[identifier] = document
        return documents
