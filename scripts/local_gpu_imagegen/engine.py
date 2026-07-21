from __future__ import annotations

import base64
import copy
import hashlib
import os
import secrets
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

from .artifacts import ensure_within, sha256_file, validate_png
from .backend_contract import validate_backend_result
from .errors import ArtifactError, AssetEngineError, ConflictError, StateError, ValidationError
from .generation_plan import validate_confirmed_run_request, validate_generation_plan
from .masks import MaskService
from .preview import MAX_PREVIEW_BYTES, PreviewResult, create_preview
from .postprocess import (
    POSTPROCESS_CLEANUP_WARNING,
    RealEsrganAdapter,
    SUPPORTED_MODELS,
    remove_postprocess_artifact,
)
from .profile_registry import ProfileRegistry
from .revisions import RevisionService
from .run_store import AttemptHandle, RunStore
from .visual_review import (
    finalization_candidate,
    require_finalization_confirmation,
    review_is_eligible,
)


BackendRunner = Callable[[dict[str, object]], dict[str, object]]
CapabilityProvider = Callable[[], dict[str, object]]


class AssetRunEngine:
    def __init__(
        self,
        registry: ProfileRegistry,
        store: RunStore,
        backend_runner: BackendRunner,
        capability_provider: CapabilityProvider,
        postprocessor: RealEsrganAdapter | None = None,
        revisions: RevisionService | None = None,
        masks: MaskService | None = None,
        *,
        catalog: object,
        router: object,
        compilers: object,
        workflows: object | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.backend_runner = backend_runner
        self.capability_provider = capability_provider
        self.catalog = catalog
        self.router = router
        self.compilers = compilers
        self.workflows = workflows if workflows is not None else getattr(catalog, "workflows", None)
        self.postprocessor = postprocessor if postprocessor is not None else RealEsrganAdapter.from_environment()
        self.revisions = revisions if revisions is not None else RevisionService(store)
        self.masks = masks if masks is not None else MaskService(store)

    def list_profiles(self, authorization_scope: str = "private") -> dict[str, object]:
        capabilities = copy.deepcopy(self.capability_provider())
        models = sorted(self.postprocessor.available_models())
        capabilities["postprocessors"] = {
            "anime_upscale": {"available": bool(models), "models": models},
        }
        return {
            **self.registry.list_catalog(),
            "models": {
                str(model["id"]): model
                for model in self.catalog.list_models(authorization_scope)
            },
            "capabilities": capabilities,
        }

    def start_run(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        profile = _required(arguments, "profile", str)
        style = _optional(arguments, "style", str, None)
        constraints = _optional(arguments, "constraints", dict, {})
        _required(arguments, "intent", str)
        _required(arguments, "backend", str)
        _required(arguments, "upscale_policy", str)
        authorization_scope = _required(arguments, "authorization_scope", str)
        route_token = _required(arguments, "route_token", str)
        model_choice = _required(arguments, "model_choice", str)
        if not model_choice.strip():
            raise ValidationError("invalid_model_choice", "model_choice must be a non-empty registered model ID.")
        max_rounds = _optional(arguments, "max_rounds", int, 3, reject_bool=True)
        if not 1 <= max_rounds <= 3:
            raise ValidationError("invalid_round_budget", "max_rounds must be an integer from 1 to 3.")
        merged = _engine_profile(self.registry.merge(profile, style, constraints))
        capabilities = self.capability_provider()
        if not isinstance(capabilities, dict) or not isinstance(capabilities.get("available_backends"), list):
            raise ValidationError("invalid_capabilities", "Capability provider must advertise available_backends.")
        available_backends = capabilities["available_backends"]
        route = self.router.confirm(route_token, model_choice)
        if not isinstance(route, dict):
            raise ValidationError("invalid_route", "Confirmed model route must be an object.")
        _validate_start_route(route, arguments, merged, authorization_scope)
        model_record = self.catalog.resolve(model_choice, authorization_scope)
        request = {
            **copy.deepcopy(arguments),
            "merged_profile": merged,
            "max_rounds": max_rounds,
            "model_choice": model_choice,
            "model_record": copy.deepcopy(model_record),
            "available_backends": copy.deepcopy(available_backends),
            "route": copy.deepcopy(route),
            "endpoint_identity": route.get("endpoint_identity"),
            "model_identity_token": route.get("identity_token"),
            "identity_strength": route.get("identity_strength"),
            "workflow_template_id": route.get("workflow_template_id"),
            "workflow_template_version": route.get("workflow_template_version"),
            "prompt_compiler_id": route.get("prompt_compiler_id"),
            "prompt_compiler_version": route.get("prompt_compiler_version"),
        }
        request = validate_confirmed_run_request(request)
        manifest = self.store.create(request)
        return {
            "ok": True,
            "run_id": manifest["run_id"],
            "state": manifest["state"],
            "max_rounds": request["max_rounds"],
            "merged_rubric": copy.deepcopy(merged["rubric"]),
            "warnings": copy.deepcopy(manifest["warnings"]),
        }

    def get_run(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        manifest = self.store.get(run_id)
        return _review_response(manifest)

    def branch_run(self, arguments: dict[str, object]) -> dict[str, object]:
        return self.revisions.branch(arguments)

    def prepare_mask(
        self,
        arguments: dict[str, object],
    ) -> tuple[dict[str, object], PreviewResult | None]:
        return self.masks.prepare(arguments)

    def confirm_mask(self, arguments: dict[str, object]) -> dict[str, object]:
        return self.masks.confirm(arguments)

    def generate_round(self, arguments: dict[str, object]) -> tuple[dict[str, object], PreviewResult | None]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        idempotency_key = _required(arguments, "idempotency_key", str)
        action = _required(arguments, "action", str)
        edit_mode = _required(arguments, "edit_mode", str)
        mask_id = _optional(arguments, "mask_id", str, None)
        if mask_id is not None and not mask_id.strip():
            raise ValidationError("invalid_mask_id", "mask_id must be a non-empty prepared mask ID.")
        seed = _required(arguments, "seed", int, reject_bool=True)
        plan_value = _required(arguments, "plan", dict)
        change_summary = _required(arguments, "change_summary", str)
        if not change_summary.strip() or len(change_summary.strip()) > 2000:
            raise ValidationError(
                "invalid_change_summary",
                "change_summary must be non-empty and concise.",
            )

        # The entire confirmed boundary is checked before begin_attempt changes the manifest.
        manifest = self.store.get(run_id)
        request = manifest.get("request")
        if not isinstance(request, dict):
            raise ArtifactError("corrupt_manifest", "Manifest request must be an object.")
        route = request.get("route")
        if not isinstance(route, dict):
            raise ArtifactError("corrupt_manifest", "Manifest route must be an object.")
        run_root = self._run_root(run_id)
        mode, execution_parameters = self._revision_execution(
            manifest,
            run_root,
            edit_mode,
            mask_id,
            seed,
        )
        plan = validate_generation_plan(plan_value, request, action, edit_mode)
        width, height = _dimensions(plan)
        current_model = self.catalog.verify_locked_route(route)
        if not isinstance(current_model, dict):
            raise ArtifactError("invalid_model_identity", "Verified model identity must be an object.")
        compiled_prompt = self.compilers.compile(
            str(route.get("prompt_compiler_id")),
            str(plan["positive_prompt"]),
            str(plan["negative_prompt"]),
        )
        if compiled_prompt.get("compiler_version") != route.get("prompt_compiler_version"):
            raise ConflictError(
                "prompt_compiler_drifted",
                "Confirmed prompt compiler version changed before generation.",
            )
        execution_plan = copy.deepcopy(plan)
        execution_plan_parameters = execution_plan.get("parameters")
        assert isinstance(execution_plan_parameters, dict)
        execution_plan_parameters.update(execution_parameters)
        round_number = _next_round_number(manifest)
        final_path = ensure_within(run_root, run_root / f"round-{round_number:02d}.png")
        pending_path = ensure_within(run_root, run_root / f"round-{round_number:02d}.pending.png")
        attempt_request = {
            "action": action,
            "seed": seed,
            "plan": plan,
            "change_summary": change_summary.strip(),
            "route": copy.deepcopy(route),
            "compiled_prompt": copy.deepcopy(compiled_prompt),
        }
        if mask_id is not None:
            attempt_request["mask_id"] = mask_id
        handle = self.store.begin_attempt(run_id, idempotency_key, attempt_request)
        if handle.status == "busy":
            raise ConflictError("run_busy", "The idempotent generation attempt is still running.", {"run_id": run_id})
        if handle.status == "completed":
            return self._return_completed(run_id, handle)

        try:
            if handle.status == "resume_preview":
                image = _existing_image(handle)
                image_metadata = self._validate_retained_image(run_root, image, width, height)
                backend_result = _existing_backend_result(handle, mode, width, height, seed, plan, request)
            else:
                pending_path.unlink(missing_ok=True)
                backend_request = _backend_request(
                    execution_plan,
                    compiled_prompt,
                    route,
                    current_model,
                    self.workflows,
                    idempotency_key,
                    seed,
                    pending_path,
                    width,
                    height,
                    mode,
                )
                backend_result = validate_backend_result(
                    self.backend_runner(backend_request),
                    mode,
                    width,
                    height,
                    expected_seed=seed,
                    expected_backend=str(route["backend"]),
                    available_backends=request["available_backends"],
                )
                _validate_locked_backend_result(backend_result, route, current_model)
                backend_path = Path(str(backend_result["path"]))
                if not backend_path.is_absolute():
                    backend_path = run_root / backend_path
                backend_path = ensure_within(run_root, backend_path)
                if backend_path != pending_path.resolve():
                    raise ArtifactError(
                        "invalid_backend_result",
                        "Backend path does not match the requested pending artifact.",
                        {"path": str(backend_path)},
                    )
                validate_png(backend_path, width, height)
                os.replace(backend_path, final_path)
                image_metadata = validate_png(final_path, width, height)
                image_metadata["path"] = final_path.name
                backend_result["path"] = final_path.name
                self.store.mark_attempt_image(handle, image_metadata, backend_result)

            preview_path = _preferred_preview_path(final_path)
            preview = create_preview(final_path, preview_path)
            preview_metadata = _preview_metadata(preview, run_root)
            warnings = [preview.warning] if preview.warning is not None else []
            completed = self.store.complete_attempt(handle, {
                **_backend_round_fields(backend_result),
                "registry_metadata": _registry_metadata(request),
                "preview": preview_metadata,
                "warnings": warnings,
            })
        except Exception as error:
            pending_path.unlink(missing_ok=True)
            self._fail_owned_attempt(handle, error)
            raise

        if warnings:
            completed = self._append_warnings(run_id, warnings)
        self.catalog.record_observation(
            str(route["model_id"]),
            str(route["identity_token"]),
            mode,
            run_id,
        )
        round_value = _round_by_number(completed, round_number)
        return _generation_result(completed, round_value, final_path), preview

    def _revision_execution(
        self,
        manifest: dict[str, object],
        run_root: Path,
        requested_mode: str,
        mask_id: str | None,
        seed: int,
    ) -> tuple[str, dict[str, object]]:
        parent = manifest.get("parent")
        revision = manifest.get("revision")
        if parent is None and revision is None:
            if requested_mode != "txt2img":
                raise ValidationError(
                    "root_edit_mode_invalid",
                    "Root runs support only txt2img generation.",
                    {"edit_mode": requested_mode},
                )
            if mask_id is not None:
                raise ValidationError("mask_not_allowed", "Root txt2img runs do not accept mask_id.")
            return "txt2img", {}
        if not isinstance(parent, dict) or not isinstance(revision, dict):
            raise ArtifactError("corrupt_manifest", "Revision lineage metadata is incomplete.")

        branch_mode = revision.get("edit_mode")
        expected_mode = {
            "prompt-refine": "txt2img",
            "img2img": "img2img",
            "inpaint": "inpaint",
        }.get(branch_mode)
        if expected_mode is None:
            raise ArtifactError("corrupt_manifest", "Revision edit mode is invalid.")
        if requested_mode != expected_mode:
            raise ValidationError(
                "revision_edit_mode_mismatch",
                "Generation edit_mode must match the immutable revision contract.",
                {"edit_mode": requested_mode, "expected": expected_mode},
            )
        if expected_mode != "inpaint" and mask_id is not None:
            raise ValidationError("mask_not_allowed", "mask_id is accepted only by inpaint revisions.")

        if branch_mode == "prompt-refine":
            rounds = manifest.get("rounds")
            if not isinstance(rounds, list):
                raise ArtifactError("corrupt_manifest", "Manifest rounds must be an array.")
            if not rounds:
                parent_run_id = parent.get("run_id")
                parent_round = parent.get("round")
                if not isinstance(parent_run_id, str) or type(parent_round) is not int:
                    raise ArtifactError("corrupt_manifest", "Revision parent reference is invalid.")
                selected = _round_by_number(self.store.get(parent_run_id), parent_round)
                parent_seed = selected.get("seed")
                if type(parent_seed) is not int:
                    raise ArtifactError("corrupt_manifest", "Revision parent seed is invalid.")
                if seed != parent_seed:
                    raise StateError(
                        "revision_seed_mismatch",
                        "The first prompt-refine round must inherit the parent seed.",
                        {"expected_seed": parent_seed},
                    )
            return "txt2img", {}

        source_path = _validated_revision_source(manifest, run_root)
        strength = revision.get("denoising_strength")
        if not isinstance(strength, (int, float)) or isinstance(strength, bool):
            raise ArtifactError("corrupt_manifest", "Revision denoising strength is invalid.")
        parameters: dict[str, object] = {
            "input_image": str(source_path),
            "strength": strength,
        }
        if expected_mode == "inpaint":
            if mask_id is None:
                raise ValidationError(
                    "inpaint_mask_required",
                    "Inpaint revisions require one confirmed child mask_id.",
                )
            mask = self.masks.confirmed_for_generation(str(manifest.get("run_id")), mask_id)
            parameters["mask_image"] = mask["mask_path"]
        return expected_mode, parameters

    def record_review(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        round_number = _required(arguments, "round_number", int, reject_bool=True)
        review = _required(arguments, "review", dict)
        manifest = self.store.record_review(run_id, round_number, review)
        return _review_response(manifest)

    def finalize_run(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        round_number = _required(arguments, "round_number", int, reject_bool=True)
        if not 1 <= round_number <= 3:
            raise ValidationError("invalid_round_number", "round_number must be an integer from 1 to 3.")
        summary = _required(arguments, "summary", str)
        if not summary.strip() or len(summary.strip()) > 2000:
            raise ValidationError("invalid_final_summary", "Final summary must be non-empty and concise.")
        confirmation = _required(arguments, "confirmation", str)
        manifest = self.store.get(run_id)
        require_finalization_confirmation(manifest, round_number, confirmation)
        postprocess = _postprocess_request(arguments.get("postprocess")) if "postprocess" in arguments else None
        if postprocess is not None:
            request = manifest.get("request")
            if not isinstance(request, dict):
                raise ArtifactError("corrupt_manifest", "Manifest request must be an object.")
            if request.get("upscale_policy") == "off":
                raise ValidationError(
                    "postprocess_disabled",
                    "Anime postprocessing is disabled by the confirmed upscale policy.",
                )
            if request.get("style") != "anime":
                raise ValidationError(
                    "postprocess_requires_anime_style",
                    "Anime postprocessing requires the confirmed anime style.",
                )
        run_root = self._run_root(run_id)
        pending_path = ensure_within(run_root, run_root / "final.pending.png")
        final_path = ensure_within(run_root, run_root / "final.png")
        upscaled_path = run_root / "final-upscaled.png"
        upscaled_pending_path = run_root / "final-upscaled.pending.png"
        backup_path = ensure_within(run_root, run_root / f".final.rollback.{secrets.token_hex(8)}.png")
        backup_created = False
        final_published = False
        postprocess_outcome: dict[str, object] | None = None

        def publish(selected: dict[str, object]) -> dict[str, object]:
            nonlocal backup_created, final_published, postprocess_outcome
            image = selected.get("image")
            if not isinstance(image, dict):
                raise ArtifactError("invalid_image_metadata", "Selected round has no full image metadata.")
            width = image.get("width")
            height = image.get("height")
            if not _exact_int(width) or not _exact_int(height) or width <= 0 or height <= 0:
                raise ArtifactError("invalid_image_metadata", "Selected round image dimensions are invalid.")
            source = self._validate_retained_image(run_root, image, width, height)
            source_path = ensure_within(run_root, run_root / str(source["path"]))
            pending_path.unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)
            shutil.copyfile(source_path, pending_path)
            validate_png(pending_path, width, height)
            if final_path.exists():
                os.replace(final_path, backup_path)
                backup_created = True
            os.replace(pending_path, final_path)
            final_published = True
            final_image = copy.deepcopy(source)
            final_image["path"] = final_path.name
            if postprocess is not None:
                model = str(postprocess["model"])
                cleanup_warnings: list[str] = []

                def note_cleanup_failure() -> None:
                    if POSTPROCESS_CLEANUP_WARNING not in cleanup_warnings:
                        cleanup_warnings.append(POSTPROCESS_CLEANUP_WARNING)

                def clean_postprocess_artifact(path: Path) -> bool:
                    removed = remove_postprocess_artifact(path)
                    if not removed:
                        note_cleanup_failure()
                    return removed

                def raise_sanitized_restore_failure(error: Exception) -> None:
                    note_cleanup_failure()
                    if isinstance(error, AssetEngineError):
                        error.details = {**error.details, "cleanup_warning": POSTPROCESS_CLEANUP_WARNING}
                        raise error
                    raise AssetEngineError(
                        "postprocess_failed",
                        "Anime postprocessor source recovery failed.",
                        "postprocess",
                        {"reason": "source_restore_failed", "cleanup_warning": POSTPROCESS_CLEANUP_WARNING},
                    ) from error

                try:
                    cleanup_results = [
                        clean_postprocess_artifact(path)
                        for path in (upscaled_pending_path, upscaled_path)
                    ]
                    cleanup_ready = all(cleanup_results)
                    if not cleanup_ready:
                        raise AssetEngineError(
                            "postprocess_failed",
                            "Anime postprocessor artifacts could not be prepared.",
                            "postprocess",
                            {"reason": "cleanup_failed"},
                        )
                    available_models = sorted(self.postprocessor.available_models())
                    if model not in available_models:
                        postprocess_outcome = {
                            "type": "anime_upscale",
                            "status": "unavailable",
                            "model": model,
                            "warnings": ["postprocess_unavailable"],
                        }
                    else:
                        result = self.postprocessor.upscale(final_path, upscaled_path, model)
                        postprocess_outcome = _final_postprocess_metadata(
                            result,
                            run_root,
                            final_image,
                            final_path,
                            upscaled_path,
                            model,
                        )
                        if not clean_postprocess_artifact(upscaled_pending_path):
                            raise AssetEngineError(
                                "postprocess_failed",
                                "Anime postprocessor pending artifact could not be cleaned.",
                                "postprocess",
                                {"reason": "cleanup_failed"},
                            )
                except Exception as error:
                    clean_postprocess_artifact(upscaled_path)
                    clean_postprocess_artifact(upscaled_pending_path)
                    if (
                        isinstance(error, AssetEngineError)
                        and error.details.get("cleanup_warning") == POSTPROCESS_CLEANUP_WARNING
                        and POSTPROCESS_CLEANUP_WARNING not in cleanup_warnings
                    ):
                        cleanup_warnings.append(POSTPROCESS_CLEANUP_WARNING)
                    if not clean_postprocess_artifact(pending_path):
                        raise_sanitized_restore_failure(error)
                    try:
                        shutil.copyfile(source_path, pending_path)
                        restored = validate_png(pending_path, width, height)
                    except (AssetEngineError, OSError):
                        raise_sanitized_restore_failure(error)
                    if restored.get("sha256") != source.get("sha256"):
                        raise_sanitized_restore_failure(error)
                    if not clean_postprocess_artifact(final_path):
                        raise_sanitized_restore_failure(error)
                    try:
                        os.replace(pending_path, final_path)
                        restored = validate_png(final_path, width, height)
                    except (AssetEngineError, OSError):
                        raise_sanitized_restore_failure(error)
                    if restored.get("sha256") != source.get("sha256"):
                        raise_sanitized_restore_failure(error)
                    code = error.code if isinstance(error, AssetEngineError) else "postprocess_failed"
                    unavailable = code == "postprocess_unavailable"
                    primary_warning = "postprocess_unavailable" if unavailable else "postprocess_failed"
                    postprocess_outcome = {
                        "type": "anime_upscale",
                        "status": "unavailable" if unavailable else "failed",
                        "model": model,
                        "warnings": [primary_warning, *cleanup_warnings],
                    }
            return final_image

        def rollback() -> None:
            remove_postprocess_artifact(upscaled_pending_path)
            if postprocess is not None:
                remove_postprocess_artifact(upscaled_path)
            final_removed = True
            if final_published or backup_created:
                final_removed = remove_postprocess_artifact(final_path)
            remove_postprocess_artifact(pending_path)
            if backup_created and final_removed:
                try:
                    os.replace(backup_path, final_path)
                except OSError:
                    pass

        def commit() -> None:
            backup_path.unlink(missing_ok=True)

        def decorate_manifest(value: dict[str, object]) -> None:
            if postprocess_outcome is None:
                return
            final = value.get("final")
            if not isinstance(final, dict):
                raise ArtifactError("corrupt_manifest", "Final selection metadata is missing.")
            outcome = copy.deepcopy(postprocess_outcome)
            warnings = outcome.pop("warnings", [])
            final["postprocess"] = outcome
            if outcome.get("status") == "completed":
                final["path"] = "final-upscaled.png"
            if isinstance(warnings, list) and all(isinstance(warning, str) for warning in warnings):
                _extend_manifest_warnings(value, warnings)

        finalized = self.store.finalize_round_published(
            run_id,
            round_number,
            summary,
            confirmation,
            publish,
            rollback,
            commit,
            decorate_manifest=decorate_manifest if postprocess is not None else None,
        )
        request = finalized.get("request", {})
        max_rounds = request.get("max_rounds") if isinstance(request, dict) else None
        final = finalized.get("final")
        delivered_path = final.get("path") if isinstance(final, dict) else final_path.name
        if not isinstance(delivered_path, str):
            raise ArtifactError("corrupt_manifest", "Final artifact path is invalid.")
        resolved_delivery = ensure_within(run_root, run_root / delivered_path)
        return {
            **finalized,
            "ok": True,
            "max_rounds": max_rounds,
            "full_image_path": str(resolved_delivery),
            "recoverable_next_actions": recoverable_next_actions(finalized),
        }

    def cleanup_run(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        scope = _required(arguments, "scope", str)
        confirmation = _required(arguments, "confirmation", str)
        self.store.cleanup(run_id, scope=scope, confirmation=confirmation)
        return {"ok": True, "run_id": run_id, "scope": scope}

    def _run_root(self, run_id: str) -> Path:
        return ensure_within(self.store.output_root, self.store.output_root / "runs" / run_id)

    def _validate_retained_image(
        self,
        run_root: Path,
        image: dict[str, object],
        width: int,
        height: int,
    ) -> dict[str, object]:
        path_value = image.get("path")
        digest = image.get("sha256")
        if not isinstance(path_value, str) or not path_value or not isinstance(digest, str):
            raise ArtifactError("invalid_image_metadata", "Retained image metadata is incomplete.")
        candidate = Path(path_value)
        if candidate.is_absolute():
            raise ArtifactError("invalid_image_path", "Retained image path must be relative.")
        path = ensure_within(run_root, run_root / candidate)
        metadata = validate_png(path, width, height)
        if metadata["sha256"] != digest:
            raise ArtifactError("image_hash_mismatch", "Retained image digest does not match the manifest.")
        metadata["path"] = path_value
        return metadata

    def _return_completed(
        self,
        run_id: str,
        handle: AttemptHandle,
    ) -> tuple[dict[str, object], PreviewResult | None]:
        round_value = handle.existing_round
        if not isinstance(round_value, dict):
            raise ArtifactError("corrupt_manifest", "Completed attempt has no retained round.")
        image = round_value.get("image")
        if not isinstance(image, dict):
            raise ArtifactError("invalid_image_metadata", "Completed round has no retained image.")
        width = image.get("width")
        height = image.get("height")
        if not _exact_int(width) or not _exact_int(height):
            raise ArtifactError("invalid_image_metadata", "Completed round dimensions are invalid.")
        run_root = self._run_root(run_id)
        retained = self._validate_retained_image(run_root, image, width, height)
        image_path = ensure_within(run_root, run_root / str(retained["path"]))
        preview = _load_retained_preview(round_value, run_root, image_path)
        if preview is None:
            preview = create_preview(image_path, _preferred_preview_path(image_path))
            preview_value = _preview_metadata(preview, run_root)
            warnings = [preview.warning] if preview.warning is not None else []

            def rebuild(value: dict[str, object]) -> None:
                stored_round = _round_by_number(value, int(round_value["round_number"]))
                stored_round["preview"] = preview_value
                stored_warnings = stored_round.get("warnings")
                if not isinstance(stored_warnings, list):
                    stored_warnings = []
                    stored_round["warnings"] = stored_warnings
                for warning in warnings:
                    if warning not in stored_warnings:
                        stored_warnings.append(warning)
                _extend_manifest_warnings(value, warnings)

            manifest = self.store.update(run_id, rebuild)
            round_value = _round_by_number(manifest, int(round_value["round_number"]))
        else:
            manifest = self.store.get(run_id)
            round_value = _round_by_number(manifest, int(round_value["round_number"]))
        return _generation_result(manifest, round_value, image_path), preview

    def _append_warnings(self, run_id: str, warnings: list[str]) -> dict[str, object]:
        return self.store.update(run_id, lambda value: _extend_manifest_warnings(value, warnings))

    def _fail_owned_attempt(self, handle: AttemptHandle, error: Exception) -> None:
        if handle.owner_token is None:
            return
        if isinstance(error, AssetEngineError):
            error_value = {
                "code": error.code,
                "message": str(error.args[0]),
                "category": error.category,
                "details": copy.deepcopy(error.details),
            }
        else:
            error_value = {
                "code": "unexpected_engine_error",
                "message": str(error) or type(error).__name__,
                "category": "internal",
            }
        try:
            self.store.fail_attempt(handle, error_value)
        except AssetEngineError:
            pass


def recoverable_next_actions(manifest: dict[str, object]) -> list[str]:
    state = manifest.get("state")
    if state == "created":
        return ["generate_round"]
    if state == "generating":
        return ["get_run", "generate_round"]
    if state == "generated":
        return ["record_review"]
    if state == "finalized":
        return ["get_run", "cleanup_run"]
    if state != "reviewed":
        return ["get_run"]
    actions: list[str] = []
    if _eligible_candidates(manifest):
        actions.append("finalize_run")
    request = manifest.get("request")
    rounds = manifest.get("rounds")
    max_rounds = request.get("max_rounds") if isinstance(request, dict) else None
    if isinstance(rounds, list) and _exact_int(max_rounds) and len(rounds) < max_rounds:
        actions.extend(("generate_round:refine", "generate_round:explore"))
    return actions or ["get_run"]


def _arguments(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("invalid_argument_type", "Tool arguments must be an object.", {"field": "arguments"})
    return value


def _postprocess_request(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"type", "model"}:
        raise ValidationError(
            "invalid_postprocess",
            "postprocess must contain exactly type and model.",
        )
    postprocess_type = value.get("type")
    model = value.get("model")
    if postprocess_type != "anime_upscale" or not isinstance(model, str) or model not in SUPPORTED_MODELS:
        raise ValidationError(
            "invalid_postprocess",
            "postprocess must request anime_upscale with a supported model.",
            {"allowed_models": sorted(SUPPORTED_MODELS)},
        )
    return {"type": postprocess_type, "model": model}


def _final_postprocess_metadata(
    result: object,
    run_root: Path,
    final_image: dict[str, object],
    source_path: Path,
    output_path: Path,
    model: str,
) -> dict[str, object]:
    if (
        not isinstance(result, dict)
        or result.get("type") != "anime_upscale"
        or result.get("model") != model
        or result.get("scale") != 4
    ):
        raise ArtifactError("invalid_postprocess_result", "Postprocessor returned invalid metadata.")
    for field, expected in (("source", source_path), ("output", output_path)):
        metadata = result.get(field)
        path_value = metadata.get("path") if isinstance(metadata, dict) else None
        if not isinstance(path_value, str):
            raise ArtifactError("invalid_postprocess_result", "Postprocessor artifact metadata is incomplete.")
        candidate = Path(path_value)
        if not candidate.is_absolute():
            candidate = run_root / candidate
        if ensure_within(run_root, candidate) != expected:
            raise ArtifactError("invalid_postprocess_result", "Postprocessor artifact path is invalid.")

    width = final_image.get("width")
    height = final_image.get("height")
    if not _exact_int(width) or not _exact_int(height) or width <= 0 or height <= 0:
        raise ArtifactError("invalid_image_metadata", "Final image dimensions are invalid.")
    source = validate_png(source_path, width, height)
    output = validate_png(output_path, width * 4, height * 4)
    if source.get("sha256") != final_image.get("sha256"):
        raise ArtifactError("image_hash_mismatch", "Postprocessor changed the immutable final source image.")
    source["path"] = source_path.relative_to(run_root).as_posix()
    output["path"] = output_path.relative_to(run_root).as_posix()
    return {
        "type": "anime_upscale",
        "status": "completed",
        "model": model,
        "scale": 4,
        "source": source,
        "output": output,
    }


def _engine_profile(merged: dict[str, object]) -> dict[str, object]:
    """Expose the nested registry policy fields consumed by RunStore and plan validation."""
    value = copy.deepcopy(merged)
    profile = value.get("profile")
    style = value.get("style")
    if not isinstance(profile, dict):
        raise ValidationError("invalid_profile_document", "Merged profile document is missing.")
    failures: list[str] = []
    for document in (profile, style):
        if not isinstance(document, dict):
            continue
        registered = document.get("hard_failures", [])
        if not isinstance(registered, list) or not all(isinstance(item, str) for item in registered):
            raise ValidationError("invalid_profile_document", "hard_failures must be a list of strings.")
        for item in registered:
            if item not in failures:
                failures.append(item)
    value["hard_failures"] = failures
    for action in ("refine", "explore"):
        mutable = profile.get(f"{action}_mutable", [])
        if not isinstance(mutable, list) or not all(isinstance(item, str) for item in mutable):
            raise ValidationError("invalid_profile_document", f"{action}_mutable must be a list of strings.")
        value[f"{action}_mutable"] = copy.deepcopy(mutable)
    return value


def _required(
    arguments: dict[str, object],
    name: str,
    expected_type: type,
    *,
    reject_bool: bool = False,
) -> object:
    if name not in arguments:
        raise ValidationError("missing_argument", f"Missing required argument: {name}.", {"field": name})
    value = arguments[name]
    if not isinstance(value, expected_type) or reject_bool and isinstance(value, bool):
        raise ValidationError("invalid_argument_type", f"Argument {name} has the wrong type.", {"field": name})
    return value


def _optional(
    arguments: dict[str, object],
    name: str,
    expected_type: type,
    default: object,
    *,
    reject_bool: bool = False,
) -> object:
    if name not in arguments:
        return copy.deepcopy(default)
    value = arguments[name]
    if value is None and default is None:
        return None
    if not isinstance(value, expected_type) or reject_bool and isinstance(value, bool):
        raise ValidationError("invalid_argument_type", f"Argument {name} has the wrong type.", {"field": name})
    return value


def _exact_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _next_round_number(manifest: dict[str, object]) -> int:
    rounds = manifest.get("rounds")
    if not isinstance(rounds, list):
        raise ArtifactError("corrupt_manifest", "Manifest rounds must be an array.")
    return len(rounds) + 1


def _dimensions(plan: dict[str, object]) -> tuple[int, int]:
    parameters = plan["parameters"]
    constraints = plan["constraints"]
    assert isinstance(parameters, dict) and isinstance(constraints, dict)
    width = parameters.get("width", constraints.get("width", 1024))
    height = parameters.get("height", constraints.get("height", 1024))
    if not _exact_int(width) or not _exact_int(height) or width < 256 or height < 256 or width > 1536 or height > 1536:
        raise ValidationError("invalid_dimensions", "Width and height must be integers from 256 to 1536.")
    if width % 8 != 0 or height % 8 != 0:
        raise ValidationError("invalid_dimensions", "Width and height must be divisible by 8.")
    return width, height


def _validated_revision_source(manifest: dict[str, object], run_root: Path) -> Path:
    revision = manifest.get("revision")
    source = revision.get("source_image") if isinstance(revision, dict) else None
    if not isinstance(source, dict):
        raise ArtifactError("corrupt_manifest", "Revision source image metadata is missing.")
    path_value = source.get("path")
    width = source.get("width")
    height = source.get("height")
    stored_hash = source.get("sha256")
    if (
        not isinstance(path_value, str)
        or Path(path_value).is_absolute()
        or type(width) is not int
        or width <= 0
        or type(height) is not int
        or height <= 0
        or not isinstance(stored_hash, str)
    ):
        raise ArtifactError("corrupt_manifest", "Revision source image metadata is invalid.")
    source_path = ensure_within(run_root, run_root / path_value)
    try:
        metadata = validate_png(source_path, width, height)
    except AssetEngineError as error:
        raise ConflictError(
            "revision_source_changed",
            "Revision source image changed after the child run was created.",
        ) from error
    if metadata["sha256"] != stored_hash:
        raise ConflictError(
            "revision_source_changed",
            "Revision source image changed after the child run was created.",
        )
    return source_path


def _validate_start_route(
    route: dict[str, object],
    arguments: dict[str, object],
    merged: dict[str, object],
    authorization_scope: str,
) -> None:
    constraints = merged.get("constraints")
    if not isinstance(constraints, dict):
        raise ValidationError("invalid_profile_document", "Merged profile constraints are missing.")
    expected = {
        "route_token": arguments.get("route_token"),
        "model_id": arguments.get("model_choice"),
        "authorization_scope": authorization_scope,
        "operation": "txt2img",
        "profile": arguments.get("profile"),
        "style": arguments.get("style"),
        "width": constraints.get("width"),
        "height": constraints.get("height"),
        "backend": arguments.get("backend"),
    }
    for field, value in expected.items():
        if route.get(field) != value:
            raise ConflictError(
                "route_confirmation_mismatch",
                "Confirmed route does not match the displayed run boundary.",
                {"field": field},
            )


def _backend_request(
    plan: dict[str, object],
    compiled_prompt: dict[str, object],
    route: dict[str, object],
    model: dict[str, object],
    workflows: object | None,
    idempotency_key: str,
    seed: int,
    output_path: Path,
    width: int,
    height: int,
    mode: str,
) -> dict[str, object]:
    parameters = plan["parameters"]
    assert isinstance(parameters, dict)
    recommended = model.get("recommended")
    if not isinstance(recommended, dict):
        recommended = {}
    steps = parameters.get("steps", recommended.get("steps", 20))
    guidance = parameters.get("guidance_scale", recommended.get("guidance", 7.0))
    sampler = parameters.get("sampler", recommended.get("sampler") or "Euler a")
    scheduler = parameters.get("scheduler", recommended.get("scheduler") or "normal")
    request: dict[str, object] = {
        "backend": route["backend"],
        "idempotency_key": idempotency_key,
        "model": copy.deepcopy(model),
        "mode": mode,
        "positive_prompt": compiled_prompt["positive_prompt"],
        "negative_prompt": compiled_prompt["negative_prompt"],
        "width": width,
        "height": height,
        "steps": steps,
        "guidance_scale": guidance,
        "sampler": sampler,
        "scheduler": scheduler,
        "seed": seed,
        "source_path": parameters.get("input_image"),
        "mask_path": parameters.get("mask_image"),
        "strength": parameters.get("strength"),
        "output_path": str(output_path),
        "prompt_compiler_id": route["prompt_compiler_id"],
        "prompt_compiler_version": route["prompt_compiler_version"],
    }
    if route["backend"] == "comfyui":
        template_id = route.get("workflow_template_id")
        if workflows is None or not isinstance(template_id, str):
            raise ArtifactError(
                "invalid_workflow_template",
                "Confirmed ComfyUI workflow is unavailable.",
            )
        request["workflow"] = workflows.resolve(
            template_id,
            str(model.get("backend_model_id")),
            mode,
            {
                "positive_prompt": request["positive_prompt"],
                "negative_prompt": request["negative_prompt"],
                "seed": seed,
                "steps": steps,
                "guidance_scale": guidance,
                "sampler": sampler,
                "scheduler": scheduler,
                "width": width,
                "height": height,
            },
        )
    return request


def _validate_locked_backend_result(
    result: dict[str, object],
    route: dict[str, object],
    model: dict[str, object],
) -> None:
    expected = {
        "backend": route.get("backend"),
        "endpoint_identity": route.get("endpoint_identity"),
        "model_identity_token": route.get("identity_token"),
        "identity_strength": route.get("identity_strength"),
        "workflow_template_id": route.get("workflow_template_id"),
        "workflow_template_version": route.get("workflow_template_version"),
        "prompt_compiler_id": route.get("prompt_compiler_id"),
        "prompt_compiler_version": route.get("prompt_compiler_version"),
        "model": model.get("backend_model_id"),
    }
    for field, value in expected.items():
        if result.get(field) != value:
            raise ArtifactError(
                "invalid_backend_result",
                "Backend result changed the confirmed model route.",
                {"field": field},
            )


def _existing_image(handle: AttemptHandle) -> dict[str, object]:
    existing = handle.existing_round
    image = existing.get("image") if isinstance(existing, dict) else None
    if not isinstance(image, dict):
        raise ArtifactError("invalid_image_metadata", "Resumable attempt has no retained image.")
    return image


def _existing_backend_result(
    handle: AttemptHandle,
    mode: str,
    width: int,
    height: int,
    seed: int,
    plan: dict[str, object],
    request: dict[str, object],
) -> dict[str, object]:
    existing = handle.existing_round
    value = existing.get("backend_result") if isinstance(existing, dict) else None
    available = request.get("available_backends")
    if not isinstance(available, list):
        raise ArtifactError("corrupt_manifest", "Confirmed available_backends must be an array.")
    result = validate_backend_result(
        value,
        mode,
        width,
        height,
        expected_seed=seed,
        expected_backend=str(plan["backend"]),
        available_backends=available,
    )
    route = request.get("route")
    model = request.get("model_record")
    if not isinstance(route, dict) or not isinstance(model, dict):
        raise ArtifactError("corrupt_manifest", "Confirmed model route is missing.")
    _validate_locked_backend_result(result, route, model)
    return result


def _backend_round_fields(result: dict[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {
        "backend": result["backend"],
        "mode": result["mode"],
        "backend_result": copy.deepcopy(result),
    }
    if "model" in result:
        fields["model"] = copy.deepcopy(result["model"])
    return fields


def _registry_metadata(request: dict[str, object]) -> dict[str, object]:
    merged = request.get("merged_profile")
    model = request.get("model_record")
    if not isinstance(merged, dict) or not isinstance(model, dict):
        raise ArtifactError("corrupt_manifest", "Run registry metadata is missing.")
    profile = merged.get("profile")
    style = merged.get("style")
    if not isinstance(profile, dict) or style is not None and not isinstance(style, dict):
        raise ArtifactError("corrupt_manifest", "Run profile metadata is invalid.")

    def identity(document: dict[str, object]) -> dict[str, object]:
        identifier = document.get("id")
        schema_version = document.get("schema_version")
        if not isinstance(identifier, str) or type(schema_version) is not int:
            raise ArtifactError("corrupt_manifest", "Registry identity metadata is invalid.")
        return {"id": identifier, "schema_version": schema_version}

    if not isinstance(model.get("id"), str) or not isinstance(model.get("source"), str):
        raise ArtifactError("corrupt_manifest", "Run model metadata is incomplete.")
    return {
        "profile": identity(profile),
        "style": identity(style) if isinstance(style, dict) else None,
        "model": {
            field: copy.deepcopy(model.get(field))
            for field in ("id", "source", "license_id", "license_url", "license_status")
        },
    }


def _preview_metadata(preview: PreviewResult, run_root: Path) -> dict[str, object] | None:
    if preview.path is None:
        return None
    path = ensure_within(run_root, preview.path)
    return {
        "path": path.relative_to(run_root).as_posix(),
        "mime_type": preview.mime_type,
        "width": preview.width,
        "height": preview.height,
        "sha256": sha256_file(path),
    }


def _preferred_preview_path(image_path: Path) -> Path:
    return image_path.with_name(f"{image_path.stem}-preview.jpg")


def _load_retained_preview(
    round_value: dict[str, object],
    run_root: Path,
    full_image_path: Path,
) -> PreviewResult | None:
    preview = round_value.get("preview")
    if (
        not isinstance(preview, dict)
        or not isinstance(preview.get("path"), str)
        or preview.get("mime_type") != "image/jpeg"
        or not isinstance(preview.get("sha256"), str)
        or len(preview["sha256"]) != 64
    ):
        return None
    candidate = Path(str(preview["path"]))
    if candidate.is_absolute():
        return None
    try:
        raw_path = run_root / candidate
        resolved_path = ensure_within(run_root, raw_path)
        contents = _trusted_preview_data(raw_path, resolved_path, full_image_path, preview["sha256"])
        if contents is None:
            return None
        payload = base64.b64encode(contents).decode("ascii")
    except (ArtifactError, OSError):
        return None
    return PreviewResult(
        resolved_path,
        preview.get("mime_type") if isinstance(preview.get("mime_type"), str) else "image/jpeg",
        payload,
        preview.get("width") if _exact_int(preview.get("width")) else None,
        preview.get("height") if _exact_int(preview.get("height")) else None,
        None,
    )


def _trusted_preview_data(
    raw_path: Path,
    resolved_path: Path,
    full_image_path: Path,
    expected_sha256: str,
) -> bytes | None:
    if _path_is_link_like(raw_path):
        return None
    raw_stat = os.stat(raw_path, follow_symlinks=False)
    if not stat.S_ISREG(raw_stat.st_mode):
        return None

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(resolved_path, flags)
    try:
        opened_stat = os.fstat(descriptor)
        full_stat = os.stat(full_image_path, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or not _same_file_identity(raw_stat, opened_stat)
            or opened_stat.st_size <= 0
            or opened_stat.st_size > MAX_PREVIEW_BYTES
            or _same_file_identity(opened_stat, full_stat)
        ):
            return None
        contents = _read_bounded_descriptor(descriptor)
        final_stat = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(contents) != opened_stat.st_size
        or not _same_descriptor_state(opened_stat, final_stat)
        or not _path_matches_open_file(raw_path, final_stat)
        or not contents.startswith(b"\xff\xd8")
        or not contents.endswith(b"\xff\xd9")
        or hashlib.sha256(contents).hexdigest() != expected_sha256
    ):
        return None
    return contents


def _read_bounded_descriptor(descriptor: int) -> bytes:
    contents = bytearray()
    while len(contents) <= MAX_PREVIEW_BYTES:
        remaining = MAX_PREVIEW_BYTES + 1 - len(contents)
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        contents.extend(chunk)
    return bytes(contents)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_ino != 0
        and right.st_ino != 0
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
    )


def _same_descriptor_state(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _same_file_identity(left, right)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _path_is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    path_stat = os.lstat(path)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _path_matches_open_file(path: Path, descriptor_stat: os.stat_result) -> bool:
    try:
        if _path_is_link_like(path):
            return False
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(current.st_mode) and _same_file_identity(current, descriptor_stat)


def _round_by_number(manifest: dict[str, object], round_number: int) -> dict[str, object]:
    rounds = manifest.get("rounds")
    if isinstance(rounds, list):
        for round_value in rounds:
            if isinstance(round_value, dict) and round_value.get("round_number") == round_number:
                return round_value
    raise ArtifactError("corrupt_manifest", "Expected generated round is missing.", {"round_number": round_number})


def _generation_result(
    manifest: dict[str, object],
    round_value: dict[str, object],
    image_path: Path,
) -> dict[str, object]:
    return {
        "ok": True,
        "run_id": manifest["run_id"],
        "state": manifest["state"],
        "round": copy.deepcopy(round_value),
        "full_image_path": str(image_path.resolve()),
        "warnings": copy.deepcopy(manifest.get("warnings", [])),
        "recoverable_next_actions": recoverable_next_actions(manifest),
    }


def _extend_manifest_warnings(manifest: dict[str, object], warnings: list[str]) -> None:
    stored = manifest.get("warnings")
    if not isinstance(stored, list):
        raise ArtifactError("corrupt_manifest", "Manifest warnings must be an array.")
    for warning in warnings:
        if warning not in stored:
            stored.append(warning)


def _reviews_by_round(manifest: dict[str, object]) -> dict[int, dict[str, object]]:
    reviews = manifest.get("reviews")
    if not isinstance(reviews, list):
        raise ArtifactError("corrupt_manifest", "Manifest reviews must be an array.")
    values: dict[int, dict[str, object]] = {}
    for review in reviews:
        if isinstance(review, dict) and _exact_int(review.get("round_number")):
            values[int(review["round_number"])] = review
    return values


def _is_eligible(manifest: dict[str, object], review: dict[str, object]) -> bool:
    return review_is_eligible(manifest, review)


def _eligible_candidates(manifest: dict[str, object]) -> list[dict[str, object]]:
    reviews = _reviews_by_round(manifest)
    rounds = manifest.get("rounds")
    if not isinstance(rounds, list):
        raise ArtifactError("corrupt_manifest", "Manifest rounds must be an array.")
    return [
        round_value for round_value in rounds
        if isinstance(round_value, dict)
        and _exact_int(round_value.get("round_number"))
        and round_value["round_number"] in reviews
        and _is_eligible(manifest, reviews[int(round_value["round_number"])])
    ]


def _review_response(manifest: dict[str, object]) -> dict[str, object]:
    response = {
        **manifest,
        "recoverable_next_actions": recoverable_next_actions(manifest),
    }
    candidates = _eligible_candidates(manifest)
    if candidates:
        round_number = candidates[-1].get("round_number")
        if isinstance(round_number, int) and not isinstance(round_number, bool):
            candidate = finalization_candidate(manifest, round_number)
            if candidate is not None:
                response["finalization_candidate"] = candidate
    return response
