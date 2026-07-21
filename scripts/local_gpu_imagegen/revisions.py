from __future__ import annotations

import copy
import math
import os
import shutil
from pathlib import Path

from .artifacts import ensure_within, sha256_file, validate_png
from .errors import ArtifactError, AssetEngineError, StateError, ValidationError
from .run_store import RunStore


REVISION_EDIT_MODES = frozenset({"prompt-refine", "img2img", "inpaint"})


def validate_revision_contract(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"preserve", "change"}:
        raise ValidationError(
            "invalid_revision_contract",
            "Revision contract requires only preserve and change.",
        )
    preserve = value["preserve"]
    change = value["change"]
    if not isinstance(preserve, list):
        raise ValidationError("invalid_revision_preserve", "preserve must be a list.")
    if not isinstance(change, list) or not change or not all(
        isinstance(item, str) and item.strip() for item in change
    ):
        raise ValidationError(
            "invalid_revision_change",
            "change must contain at least one non-empty string.",
        )

    normalized_preserve: list[dict[str, str]] = []
    preserve_keys: set[str] = set()
    for item in preserve:
        if not isinstance(item, dict) or set(item) != {"target", "strength"}:
            raise ValidationError(
                "invalid_preserve_item",
                "Each preserve item requires target and strength.",
            )
        target = item["target"]
        if not isinstance(target, str) or not target.strip():
            raise ValidationError("invalid_preserve_target", "Preserve target must be non-empty.")
        strength = item["strength"]
        if not isinstance(strength, str) or strength not in {"hard", "soft"}:
            raise ValidationError(
                "invalid_preserve_strength",
                "Preserve strength must be hard or soft.",
            )
        normalized_target = target.strip()
        target_key = normalized_target.casefold()
        if target_key in preserve_keys:
            raise ValidationError(
                "duplicate_revision_item",
                "Preserve targets and requested changes must be unique after case-folding.",
            )
        preserve_keys.add(target_key)
        normalized_preserve.append({"target": normalized_target, "strength": strength})

    normalized_change = [item.strip() for item in change]
    change_keys = [item.casefold() for item in normalized_change]
    if len(set(change_keys)) != len(change_keys):
        raise ValidationError(
            "duplicate_revision_item",
            "Preserve targets and requested changes must be unique after case-folding.",
        )
    return {"preserve": normalized_preserve, "change": normalized_change}


class RevisionService:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def branch(self, arguments: dict[str, object]) -> dict[str, object]:
        normalized = self._validate_arguments(arguments)
        parent_id = normalized["parent_run_id"]
        parent_round = normalized["parent_round"]
        assert isinstance(parent_id, str)
        assert isinstance(parent_round, int)

        parent = self.store.get(parent_id)
        selected = self._reviewed_parent_round(parent, parent_round)
        parent_image, source_path = self._validated_parent_image(parent_id, selected)

        request = parent.get("request")
        if not isinstance(request, dict):
            raise ArtifactError("corrupt_manifest", "Parent request must be an object.")
        child_request = copy.deepcopy(request)
        child_request["max_rounds"] = normalized["max_rounds"]

        child = self.store.create(child_request)
        child_id = child["run_id"]
        assert isinstance(child_id, str)
        child_root = self.store.run_root(child_id)
        pending_path = ensure_within(child_root, child_root / "parent-source.pending.png")
        final_path = ensure_within(child_root, child_root / "parent-source.png")
        try:
            shutil.copyfile(source_path, pending_path)
            copied = validate_png(
                pending_path,
                parent_image["width"],
                parent_image["height"],
            )
            if copied["sha256"] != parent_image["sha256"]:
                raise ArtifactError(
                    "revision_parent_image_changed",
                    "Parent image changed while the revision branch was being created.",
                    {"run_id": parent_id, "round_number": parent_round},
                )
            os.replace(pending_path, final_path)
            source_image = copy.deepcopy(copied)
            source_image["path"] = "parent-source.png"

            def record_lineage(manifest: dict[str, object]) -> None:
                manifest["parent"] = {
                    "run_id": parent_id,
                    "round": parent_round,
                    "image_sha256": parent_image["sha256"],
                }
                manifest["revision"] = {
                    "contract": copy.deepcopy(normalized["contract"]),
                    "edit_mode": normalized["edit_mode"],
                    "denoising_strength": normalized.get("denoising_strength"),
                    "source_image": source_image,
                }

            return self.store.update(child_id, record_lineage)
        except Exception:
            try:
                self.store.cleanup(child_id, scope="all", confirmation=child_id)
            except AssetEngineError:
                pass
            raise
        finally:
            try:
                pending_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _validate_arguments(arguments: object) -> dict[str, object]:
        required = {"parent_run_id", "parent_round", "contract", "max_rounds", "edit_mode"}
        allowed = required | {"denoising_strength"}
        if not isinstance(arguments, dict) or not required <= set(arguments) or not set(arguments) <= allowed:
            raise ValidationError(
                "invalid_revision_arguments",
                "Revision arguments require parent, contract, round budget, and edit mode fields only.",
            )
        parent_id = arguments["parent_run_id"]
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise ValidationError("invalid_parent_run_id", "parent_run_id must be a non-empty string.")
        parent_round = arguments["parent_round"]
        if type(parent_round) is not int or not 1 <= parent_round <= 3:
            raise ValidationError("invalid_round_number", "parent_round must be an integer from 1 to 3.")
        max_rounds = arguments["max_rounds"]
        if type(max_rounds) is not int or not 1 <= max_rounds <= 3:
            raise ValidationError("invalid_round_budget", "max_rounds must be an integer from 1 to 3.")
        edit_mode = arguments["edit_mode"]
        if not isinstance(edit_mode, str) or edit_mode not in REVISION_EDIT_MODES:
            raise ValidationError(
                "invalid_revision_edit_mode",
                "edit_mode must be prompt-refine, img2img, or inpaint.",
            )

        has_strength = "denoising_strength" in arguments
        strength = arguments.get("denoising_strength")
        if edit_mode == "prompt-refine" and has_strength:
            raise ValidationError(
                "invalid_denoising_strength",
                "Prompt refinement does not accept denoising_strength.",
            )
        if edit_mode in {"img2img", "inpaint"} and (
            not isinstance(strength, (int, float))
            or isinstance(strength, bool)
            or not math.isfinite(strength)
            or not 0 < strength <= 1
        ):
            raise ValidationError(
                "invalid_denoising_strength",
                "img2img and inpaint require denoising_strength greater than 0 and at most 1.",
            )
        return {
            **copy.deepcopy(arguments),
            "parent_run_id": parent_id.strip(),
            "contract": validate_revision_contract(arguments["contract"]),
        }

    @staticmethod
    def _reviewed_parent_round(
        parent: dict[str, object],
        parent_round: int,
    ) -> dict[str, object]:
        rounds = parent.get("rounds")
        reviews = parent.get("reviews")
        if not isinstance(rounds, list) or not isinstance(reviews, list):
            raise ArtifactError("corrupt_manifest", "Parent rounds and reviews must be arrays.")
        selected = next(
            (
                value for value in rounds
                if isinstance(value, dict)
                and value.get("round_number") == parent_round
                and value.get("status") == "generated"
            ),
            None,
        )
        reviewed = any(
            isinstance(value, dict) and value.get("round_number") == parent_round
            for value in reviews
        )
        if selected is None or not reviewed:
            raise StateError(
                "revision_parent_not_reviewed",
                "Revision parent round must exist, be successful, and have a recorded review.",
                {"round_number": parent_round},
            )
        return selected

    def _validated_parent_image(
        self,
        parent_id: str,
        selected: dict[str, object],
    ) -> tuple[dict[str, object], Path]:
        image = selected.get("image")
        if not isinstance(image, dict):
            raise ArtifactError("corrupt_manifest", "Revision parent image metadata is missing.")
        path_value = image.get("path")
        width = image.get("width")
        height = image.get("height")
        stored_hash = image.get("sha256")
        if (
            not isinstance(path_value, str)
            or Path(path_value).is_absolute()
            or type(width) is not int
            or width <= 0
            or type(height) is not int
            or height <= 0
            or not isinstance(stored_hash, str)
        ):
            raise ArtifactError("corrupt_manifest", "Revision parent image metadata is invalid.")
        parent_root = self.store.run_root(parent_id)
        source_path = ensure_within(parent_root, parent_root / path_value)
        try:
            current_hash = sha256_file(source_path)
        except OSError as error:
            raise ArtifactError(
                "revision_parent_image_unavailable",
                "Revision parent image cannot be read.",
            ) from error
        if current_hash != stored_hash:
            raise ArtifactError(
                "revision_parent_image_changed",
                "Revision parent image no longer matches its retained hash.",
                {"run_id": parent_id, "path": path_value},
            )
        validated = validate_png(source_path, width, height)
        if validated["sha256"] != stored_hash:
            raise ArtifactError(
                "revision_parent_image_changed",
                "Revision parent image no longer matches its retained hash.",
            )
        validated["path"] = path_value
        return validated, source_path
