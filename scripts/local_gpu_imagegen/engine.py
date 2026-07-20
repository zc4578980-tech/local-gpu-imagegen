from __future__ import annotations

import base64
import copy
import json
import os
import secrets
import shutil
from collections.abc import Callable
from pathlib import Path

from .artifacts import ensure_within, sha256_file, validate_png
from .backend_contract import validate_backend_result
from .errors import ArtifactError, AssetEngineError, ConflictError, StateError, ValidationError
from .generation_plan import validate_confirmed_run_request, validate_generation_plan
from .preview import MAX_PREVIEW_BYTES, PreviewResult, create_preview
from .profile_registry import ProfileRegistry
from .run_store import AttemptHandle, RunStore


BackendRunner = Callable[[list[str]], tuple[int, str, str]]
CapabilityProvider = Callable[[], dict[str, object]]


class AssetRunEngine:
    def __init__(
        self,
        registry: ProfileRegistry,
        store: RunStore,
        backend_runner: BackendRunner,
        capability_provider: CapabilityProvider,
    ) -> None:
        self.registry = registry
        self.store = store
        self.backend_runner = backend_runner
        self.capability_provider = capability_provider

    def list_profiles(self) -> dict[str, object]:
        return {
            **self.registry.list_catalog(),
            "capabilities": copy.deepcopy(self.capability_provider()),
        }

    def start_run(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        profile = _required(arguments, "profile", str)
        style = _optional(arguments, "style", str, None)
        constraints = _optional(arguments, "constraints", dict, {})
        _required(arguments, "intent", str)
        _required(arguments, "model_choice", str)
        _required(arguments, "backend", str)
        available_backends = _required(arguments, "available_backends", list)
        _required(arguments, "upscale_policy", str)
        max_rounds = _optional(arguments, "max_rounds", int, 3, reject_bool=True)
        if not 1 <= max_rounds <= 3:
            raise ValidationError("invalid_round_budget", "max_rounds must be an integer from 1 to 3.")
        if not all(isinstance(value, str) for value in available_backends):
            raise ValidationError("invalid_argument_type", "available_backends must contain only strings.")
        merged = _engine_profile(self.registry.merge(profile, style, constraints))
        request = {
            **copy.deepcopy(arguments),
            "merged_profile": merged,
            "max_rounds": max_rounds,
        }
        request = validate_confirmed_run_request(request)
        capabilities = self.capability_provider()
        if not isinstance(capabilities, dict) or not isinstance(capabilities.get("available_backends"), list):
            raise ValidationError("invalid_capabilities", "Capability provider must advertise available_backends.")
        provider_backends = capabilities["available_backends"]
        if (
            not all(isinstance(value, str) for value in provider_backends)
            or len(set(provider_backends)) != len(provider_backends)
            or set(provider_backends) != set(request["available_backends"])
        ):
            raise ValidationError(
                "inconsistent_capabilities",
                "Confirmed available_backends must match the capability provider.",
            )
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
        return {**manifest, "recoverable_next_actions": recoverable_next_actions(manifest)}

    def generate_round(self, arguments: dict[str, object]) -> tuple[dict[str, object], PreviewResult | None]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        idempotency_key = _required(arguments, "idempotency_key", str)
        action = _required(arguments, "action", str)
        seed = _required(arguments, "seed", int, reject_bool=True)
        plan_value = _required(arguments, "plan", dict)

        # The entire confirmed boundary is checked before begin_attempt changes the manifest.
        manifest = self.store.get(run_id)
        request = manifest.get("request")
        if not isinstance(request, dict):
            raise ArtifactError("corrupt_manifest", "Manifest request must be an object.")
        plan = validate_generation_plan(plan_value, request, action)
        width, height = _dimensions(plan)
        mode = _mode(plan)
        run_root = self._run_root(run_id)
        round_number = _next_round_number(manifest)
        final_path = ensure_within(run_root, run_root / f"round-{round_number:02d}.png")
        pending_path = ensure_within(run_root, run_root / f"round-{round_number:02d}.pending.png")
        attempt_request = {"action": action, "seed": seed, "plan": plan}
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
                command = _backend_arguments(plan, seed, run_root, pending_path.name, width, height, mode)
                return_code, stdout, stderr = self.backend_runner(command)
                if return_code != 0:
                    raise AssetEngineError(
                        "backend_command_failed",
                        "Image backend command failed.",
                        "backend",
                        {"exit_code": return_code, "stderr": stderr},
                    )
                backend_result = _parse_backend_stdout(stdout, mode, width, height, seed, plan, request)
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

            preview_path = final_path.with_suffix(".preview.jpg")
            preview = create_preview(final_path, preview_path)
            preview_metadata = _preview_metadata(preview, run_root)
            warnings = [preview.warning] if preview.warning is not None else []
            completed = self.store.complete_attempt(handle, {
                **_backend_round_fields(backend_result),
                "preview": preview_metadata,
                "warnings": warnings,
            })
        except Exception as error:
            pending_path.unlink(missing_ok=True)
            self._fail_owned_attempt(handle, error)
            raise

        if warnings:
            completed = self._append_warnings(run_id, warnings)
        round_value = _round_by_number(completed, round_number)
        return _generation_result(completed, round_value, final_path), preview

    def record_review(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        round_number = _required(arguments, "round_number", int, reject_bool=True)
        review = _required(arguments, "review", dict)
        manifest = self.store.record_review(run_id, round_number, review)
        return {**manifest, "recoverable_next_actions": recoverable_next_actions(manifest)}

    def finalize_run(self, arguments: dict[str, object]) -> dict[str, object]:
        arguments = _arguments(arguments)
        run_id = _required(arguments, "run_id", str)
        summary = _required(arguments, "summary", str)
        if not summary.strip() or len(summary.strip()) > 2000:
            raise ValidationError("invalid_final_summary", "Final summary must be non-empty and concise.")
        manifest = self.store.get(run_id)
        if manifest.get("state") == "finalized" or manifest.get("final") is not None:
            raise StateError("already_finalized", "Run already has a final selection.")
        selected = _select_final_candidate(manifest)
        run_root = self._run_root(run_id)
        image = selected.get("image")
        if not isinstance(image, dict):
            raise ArtifactError("invalid_image_metadata", "Selected round has no full image metadata.")
        width = image.get("width")
        height = image.get("height")
        if not _exact_int(width) or not _exact_int(height) or width <= 0 or height <= 0:
            raise ArtifactError("invalid_image_metadata", "Selected round image dimensions are invalid.")
        source = self._validate_retained_image(run_root, image, width, height)
        source_path = ensure_within(run_root, run_root / str(source["path"]))
        pending_path = ensure_within(run_root, run_root / "final.pending.png")
        final_path = ensure_within(run_root, run_root / "final.png")
        backup_path = ensure_within(run_root, run_root / f".final.rollback.{secrets.token_hex(8)}.png")
        final_image = copy.deepcopy(source)
        final_image["path"] = final_path.name
        backup_created = False
        final_published = False

        def publish() -> None:
            nonlocal backup_created, final_published
            pending_path.unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)
            shutil.copyfile(source_path, pending_path)
            validate_png(pending_path, width, height)
            if final_path.exists():
                os.replace(final_path, backup_path)
                backup_created = True
            os.replace(pending_path, final_path)
            final_published = True

        def rollback() -> None:
            if final_published:
                final_path.unlink(missing_ok=True)
            pending_path.unlink(missing_ok=True)
            if backup_created and backup_path.exists():
                os.replace(backup_path, final_path)

        def commit() -> None:
            backup_path.unlink(missing_ok=True)

        finalized = self.store.finalize_published(
            run_id,
            int(selected["round_number"]),
            summary,
            final_image,
            publish,
            rollback,
            commit,
        )
        request = finalized.get("request", {})
        max_rounds = request.get("max_rounds") if isinstance(request, dict) else None
        return {
            **finalized,
            "ok": True,
            "max_rounds": max_rounds,
            "full_image_path": str(final_path.resolve()),
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
            preview = create_preview(image_path, image_path.with_suffix(".preview.jpg"))
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
    elif not actions and isinstance(rounds, list) and rounds:
        actions.append("finalize_run")
    return actions


def _arguments(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("invalid_argument_type", "Tool arguments must be an object.", {"field": "arguments"})
    return value


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


def _mode(plan: dict[str, object]) -> str:
    parameters = plan["parameters"]
    assert isinstance(parameters, dict)
    mode = parameters.get("mode", "txt2img")
    if not isinstance(mode, str) or mode not in {"txt2img", "img2img", "inpaint"}:
        raise ValidationError("invalid_mode", "Generation mode must be txt2img, img2img, or inpaint.")
    return mode


def _backend_arguments(
    plan: dict[str, object],
    seed: int,
    output_dir: Path,
    filename: str,
    width: int,
    height: int,
    mode: str,
) -> list[str]:
    parameters = plan["parameters"]
    assert isinstance(parameters, dict)
    values: list[tuple[str, object]] = [
        ("--prompt", plan["positive_prompt"]),
        ("--negative-prompt", plan["negative_prompt"]),
        ("--model", plan["model_choice"]),
        ("--backend", plan["backend"]),
        ("--mode", mode),
        ("--width", width),
        ("--height", height),
        ("--seed", seed),
        ("--output-dir", str(output_dir)),
        ("--filename", filename),
    ]
    mappings = {
        "steps": "--steps",
        "guidance_scale": "--guidance-scale",
        "scheduler": "--scheduler",
        "input_image": "--input-image",
        "mask_image": "--mask-image",
        "strength": "--strength",
    }
    for name, flag in mappings.items():
        if name in parameters and parameters[name] is not None:
            values.append((flag, parameters[name]))
    command: list[str] = []
    for flag, value in values:
        command.extend((flag, str(value)))
    return command


def _parse_backend_stdout(
    stdout: str,
    mode: str,
    width: int,
    height: int,
    seed: int,
    plan: dict[str, object],
    request: dict[str, object],
) -> dict[str, object]:
    try:
        value = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise ArtifactError("invalid_backend_result", "Backend stdout must be one JSON result object.") from error
    available = request.get("available_backends")
    if not isinstance(available, list):
        raise ArtifactError("corrupt_manifest", "Confirmed available_backends must be an array.")
    return validate_backend_result(
        value,
        mode,
        width,
        height,
        expected_seed=seed,
        expected_backend=str(plan["backend"]),
        available_backends=available,
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
    return validate_backend_result(
        value,
        mode,
        width,
        height,
        expected_seed=seed,
        expected_backend=str(plan["backend"]),
        available_backends=available,
    )


def _backend_round_fields(result: dict[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {
        "backend": result["backend"],
        "mode": result["mode"],
        "backend_result": copy.deepcopy(result),
    }
    if "model" in result:
        fields["model"] = copy.deepcopy(result["model"])
    return fields


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
        path = ensure_within(run_root, run_root / candidate)
        if path.is_symlink() or not path.is_file() or os.path.samefile(path, full_image_path):
            return None
        size = path.stat().st_size
        if size <= 0 or size > MAX_PREVIEW_BYTES:
            return None
        contents = path.read_bytes()
        if not contents.startswith(b"\xff\xd8") or not contents.endswith(b"\xff\xd9"):
            return None
        if sha256_file(path) != preview["sha256"]:
            return None
        payload = base64.b64encode(contents).decode("ascii")
    except (ArtifactError, OSError):
        return None
    return PreviewResult(
        path,
        preview.get("mime_type") if isinstance(preview.get("mime_type"), str) else "image/jpeg",
        payload,
        preview.get("width") if _exact_int(preview.get("width")) else None,
        preview.get("height") if _exact_int(preview.get("height")) else None,
        None,
    )


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
    failures = review.get("hard_failures")
    scores = review.get("scores")
    request = manifest.get("request")
    merged = request.get("merged_profile") if isinstance(request, dict) else None
    rubric = merged.get("rubric") if isinstance(merged, dict) else None
    if not isinstance(failures, list) or not isinstance(scores, dict) or not isinstance(rubric, dict):
        raise ArtifactError("corrupt_manifest", "Stored review eligibility data is invalid.")
    critical = [name for name, specification in rubric.items() if isinstance(specification, dict) and specification.get("critical") is True]
    return not failures and all(_exact_int(scores.get(name)) and scores[name] >= 3 for name in critical)


def _weighted_score(manifest: dict[str, object], review: dict[str, object]) -> float:
    request = manifest.get("request")
    merged = request.get("merged_profile") if isinstance(request, dict) else None
    rubric = merged.get("rubric") if isinstance(merged, dict) else None
    scores = review.get("scores")
    if not isinstance(rubric, dict) or not isinstance(scores, dict):
        raise ArtifactError("corrupt_manifest", "Stored weighted review data is invalid.")
    total = 0.0
    for name, specification in rubric.items():
        weight = specification.get("weight", 1) if isinstance(specification, dict) else 1
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ArtifactError("corrupt_manifest", "Rubric weight must be numeric.")
        score = scores.get(name)
        if not _exact_int(score):
            raise ArtifactError("corrupt_manifest", "Review score must be an integer.")
        total += float(weight) * score
    return total


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


def _select_final_candidate(manifest: dict[str, object]) -> dict[str, object]:
    reviews = _reviews_by_round(manifest)
    rounds = manifest.get("rounds")
    request = manifest.get("request")
    if not isinstance(rounds, list) or not isinstance(request, dict):
        raise ArtifactError("corrupt_manifest", "Run selection data is invalid.")
    reviewed = [
        value for value in rounds
        if isinstance(value, dict)
        and _exact_int(value.get("round_number"))
        and int(value["round_number"]) in reviews
    ]
    if not reviewed:
        raise StateError("round_requires_review", "At least one generated round must be reviewed.")
    eligible = [value for value in reviewed if _is_eligible(manifest, reviews[int(value["round_number"])])]
    candidates = eligible
    max_rounds = request.get("max_rounds")
    if not candidates:
        if not _exact_int(max_rounds) or len(rounds) < max_rounds:
            raise StateError("no_eligible_round", "No eligible reviewed round is available before the budget is exhausted.")
        candidates = reviewed
    return max(
        candidates,
        key=lambda value: (
            _weighted_score(manifest, reviews[int(value["round_number"])]),
            -int(value["round_number"]),
        ),
    )
