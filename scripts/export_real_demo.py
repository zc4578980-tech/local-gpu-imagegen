#!/usr/bin/env python
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
from pathlib import Path

from local_gpu_imagegen.artifacts import sha256_file, validate_png
from local_gpu_imagegen.errors import ValidationError
from local_gpu_imagegen.generation_plan import (
    validate_confirmed_run_request,
    validate_generation_plan,
)
from local_gpu_imagegen.visual_review import finalization_candidate, visual_checks_pass
from validate_client_sessions import validate_session
from validate_real_demo import (
    ARTIFACT_FILES,
    BUNDLE_SHA256,
    EXPECTED_FILES,
    EXPECTED_RIGHTS,
    EXPECTED_ROUTE,
    EXPECTED_SERVER_VERSION,
    MIME_TYPES,
    MODEL_ID,
    MODEL_SHA256,
    WORKFLOW_SHA256,
    validate_real_demo,
)


KNOWN_LIMITATIONS = [
    "This showcase records one observed local Windows and ComfyUI configuration.",
    "SDXL 1.0 Base is used without an SDXL refiner or automatic upscale pass.",
    "One accepted image does not establish a general image-quality or success-rate claim.",
    "The complete nine-root plus three-revision public acceptance matrix remains outside this preview.",
]


def _safe_regular_file(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return (
        stat.S_ISREG(path_stat.st_mode)
        and not stat.S_ISLNK(path_stat.st_mode)
        and not bool(attributes & reparse_flag)
    )


def _safe_directory(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return (
        stat.S_ISDIR(path_stat.st_mode)
        and not stat.S_ISLNK(path_stat.st_mode)
        and not bool(attributes & reparse_flag)
    )


def _read_json_snapshot(path: Path, code: str) -> tuple[dict[str, object], str]:
    if not _safe_regular_file(path):
        raise ValueError(code)
    try:
        encoded = path.read_bytes()
        value = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value, hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path, code: str) -> dict[str, object]:
    return _read_json_snapshot(path, code)[0]


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _selected(
    manifest: dict[str, object],
    round_number: int,
) -> tuple[dict[str, object], dict[str, object]]:
    rounds = manifest.get("rounds")
    reviews = manifest.get("reviews")
    if not isinstance(rounds, list) or not isinstance(reviews, list):
        raise ValueError("invalid_run_manifest")
    selected = next(
        (
            item
            for item in rounds
            if isinstance(item, dict)
            and item.get("round_number") == round_number
            and item.get("status") == "generated"
        ),
        None,
    )
    review = next(
        (
            item
            for item in reviews
            if isinstance(item, dict) and item.get("round_number") == round_number
        ),
        None,
    )
    if selected is None or review is None:
        raise ValueError("invalid_run_manifest")
    return selected, review


def _safe_artifact(
    run_root: Path,
    metadata: object,
    *,
    mime_type: str,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> Path:
    if not isinstance(metadata, dict):
        raise ValueError("invalid_source_artifact")
    relative = metadata.get("path")
    stored_sha256 = metadata.get("sha256")
    if (
        not isinstance(relative, str)
        or Path(relative).is_absolute()
        or not isinstance(stored_sha256, str)
        or metadata.get("mime_type") != mime_type
    ):
        raise ValueError("invalid_source_artifact")
    root = run_root.resolve()
    path = root / relative
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError("invalid_source_artifact") from exc
    if resolved.parent != root or not _safe_regular_file(path):
        raise ValueError("invalid_source_artifact")
    if sha256_file(path) != stored_sha256:
        raise ValueError("source_artifact_sha256_mismatch")
    if mime_type == "image/png":
        if expected_width is None or expected_height is None:
            raise ValueError("invalid_source_artifact")
        validated = validate_png(path, expected_width, expected_height)
        if validated["sha256"] != stored_sha256:
            raise ValueError("source_artifact_sha256_mismatch")
    else:
        data = path.read_bytes()
        if (
            len(data) > 1024 * 1024
            or not data.startswith(b"\xff\xd8")
            or not data.endswith(b"\xff\xd9")
        ):
            raise ValueError("invalid_source_preview")
    return path


def _public_authority(path: Path) -> dict[str, str]:
    authority = _read_json(path, "invalid_public_authority")
    backend = authority.get("backend")
    if (
        authority.get("status") != "approved"
        or not isinstance(backend, dict)
        or backend.get("type") != "comfyui"
        or backend.get("local") is not True
    ):
        raise ValueError("invalid_public_authority")
    models = authority.get("models")
    if not isinstance(models, list):
        raise ValueError("invalid_public_authority")
    model = next(
        (item for item in models if isinstance(item, dict) and item.get("id") == MODEL_ID),
        None,
    )
    workflow = model.get("workflow") if isinstance(model, dict) else None
    if (
        not isinstance(model, dict)
        or model.get("sha256") != MODEL_SHA256
        or model.get("use_approved") is not True
        or model.get("output_redistribution_status") != "approved"
        or model.get("component_bundle_sha256") != BUNDLE_SHA256
        or not isinstance(workflow, dict)
        or workflow.get("template_id") != "sdxl-txt2img"
        or workflow.get("template_version") != 1
        or workflow.get("sha256") != WORKFLOW_SHA256
    ):
        raise ValueError("invalid_public_authority")
    rights = {
        "source": model.get("source"),
        "license_id": model.get("license_id"),
        "license_url": model.get("license_url"),
        "output_redistribution_status": model.get("output_redistribution_status"),
    }
    if rights != EXPECTED_RIGHTS:
        raise ValueError("invalid_public_authority")
    return rights


def _public_route(
    manifest: dict[str, object],
    selected: dict[str, object],
) -> dict[str, object]:
    request = manifest.get("request")
    if not isinstance(request, dict):
        raise ValueError("invalid_public_route")
    try:
        validate_confirmed_run_request(request)
    except ValidationError as exc:
        raise ValueError("invalid_public_route") from exc
    route = request.get("route")
    backend_result = selected.get("backend_result")
    if not isinstance(route, dict) or not isinstance(backend_result, dict):
        raise ValueError("invalid_public_route")
    component_bundle = route.get("component_bundle")
    workflow = component_bundle.get("workflow") if isinstance(component_bundle, dict) else None
    if (
        not isinstance(component_bundle, dict)
        or component_bundle.get("bundle_sha256") != route.get("component_bundle_sha256")
        or not isinstance(workflow, dict)
        or workflow.get("template_id") != "sdxl-txt2img"
        or workflow.get("template_version") != 1
    ):
        raise ValueError("invalid_public_route")
    observed = {
        "authorization_scope": request.get("authorization_scope"),
        "backend": request.get("backend"),
        "model_id": request.get("model_choice"),
        "model_identity_token": request.get("model_identity_token"),
        "model_sha256": route.get("sha256"),
        "workflow_template_id": request.get("workflow_template_id"),
        "workflow_template_version": request.get("workflow_template_version"),
        "workflow_sha256": workflow.get("sha256"),
        "component_bundle_sha256": route.get("component_bundle_sha256"),
        "prompt_compiler_id": request.get("prompt_compiler_id"),
        "prompt_compiler_version": request.get("prompt_compiler_version"),
    }
    if observed != EXPECTED_ROUTE:
        raise ValueError("invalid_public_route")
    backend_identity = {
        "backend": backend_result.get("backend"),
        "model_id": backend_result.get("model"),
        "model_identity_token": backend_result.get("model_identity_token"),
        "workflow_template_id": backend_result.get("workflow_template_id"),
        "workflow_template_version": backend_result.get("workflow_template_version"),
        "prompt_compiler_id": backend_result.get("prompt_compiler_id"),
        "prompt_compiler_version": backend_result.get("prompt_compiler_version"),
    }
    if backend_identity != {
        "backend": "comfyui",
        "model_id": MODEL_ID,
        "model_identity_token": EXPECTED_ROUTE["model_identity_token"],
        "workflow_template_id": "sdxl-txt2img",
        "workflow_template_version": 1,
        "prompt_compiler_id": EXPECTED_ROUTE["prompt_compiler_id"],
        "prompt_compiler_version": EXPECTED_ROUTE["prompt_compiler_version"],
    }:
        raise ValueError("invalid_public_route")
    return copy.deepcopy(observed)


def _generation_provenance(
    manifest: dict[str, object],
    selected: dict[str, object],
) -> dict[str, object]:
    request = manifest.get("request")
    route = request.get("route") if isinstance(request, dict) else None
    locked = route.get("recommended_settings") if isinstance(route, dict) else None
    plan = selected.get("generation_plan")
    backend = selected.get("backend_result")
    compiled = selected.get("compiled_prompt")
    if (
        not isinstance(locked, dict)
        or not isinstance(plan, dict)
        or not isinstance(backend, dict)
        or not isinstance(compiled, dict)
    ):
        raise ValueError("invalid_generation_provenance")
    action = selected.get("action")
    edit_mode = backend.get("mode")
    if not isinstance(action, str) or edit_mode != "txt2img":
        raise ValueError("invalid_generation_provenance")
    try:
        validated_plan = validate_generation_plan(plan, request, action, edit_mode)
    except ValidationError as exc:
        raise ValueError("invalid_generation_provenance") from exc
    positive = validated_plan.get("positive_prompt")
    negative = validated_plan.get("negative_prompt")
    seed = selected.get("seed")
    generation = {
        "positive_prompt": positive,
        "negative_prompt": negative,
        "seed": seed,
        "width": backend.get("width"),
        "height": backend.get("height"),
        "steps": backend.get("steps"),
        "guidance_scale": backend.get("guidance_scale"),
        "sampler": backend.get("sampler"),
        "scheduler": backend.get("scheduler"),
    }
    if (
        not isinstance(positive, str)
        or not positive.strip()
        or not isinstance(negative, str)
        or not negative.strip()
        or compiled.get("positive") != positive
        or compiled.get("negative") != negative
        or not isinstance(seed, int)
        or isinstance(seed, bool)
        or seed < 0
        or backend.get("seed") != seed
        or generation["width"] != route.get("width")
        or generation["height"] != route.get("height")
        or generation["steps"] != locked.get("steps")
        or generation["guidance_scale"] != locked.get("guidance")
        or generation["sampler"] != locked.get("sampler")
        or generation["scheduler"] != locked.get("scheduler")
    ):
        raise ValueError("invalid_generation_provenance")
    parameters = validated_plan.get("parameters")
    if parameters is not None:
        if not isinstance(parameters, dict):
            raise ValueError("invalid_generation_provenance")
        for field, value in generation.items():
            if field in {"positive_prompt", "negative_prompt"}:
                continue
            if field in parameters and parameters[field] != value:
                raise ValueError("invalid_generation_provenance")
    return generation


def _sanitized_review(
    review: dict[str, object],
    manifest: dict[str, object],
) -> dict[str, object]:
    request = manifest.get("request")
    merged = request.get("merged_profile") if isinstance(request, dict) else None
    rubric = merged.get("rubric") if isinstance(merged, dict) else None
    constraints = request.get("constraints") if isinstance(request, dict) else None
    scores = review.get("scores")
    constraint_results = review.get("constraint_results")
    if (
        not isinstance(rubric, dict)
        or not rubric
        or not isinstance(constraints, dict)
        or not constraints
        or not all(isinstance(name, str) and name.strip() for name in constraints)
        or not isinstance(scores, dict)
        or set(scores) != set(rubric)
        or not isinstance(constraint_results, dict)
        or set(constraint_results) != set(constraints)
    ):
        raise ValueError("invalid_review_evidence")
    public_rubric: dict[str, dict[str, object]] = {}
    for name, specification in rubric.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(specification, dict)
            or not isinstance(specification.get("critical"), bool)
            or not isinstance(specification.get("weight"), (int, float))
            or isinstance(specification.get("weight"), bool)
            or not math.isfinite(specification["weight"])
            or specification["weight"] <= 0
        ):
            raise ValueError("invalid_review_evidence")
        public_rubric[name] = {
            "critical": specification["critical"],
            "weight": specification["weight"],
        }
    fields = (
        "round_number",
        "reviewed_at",
        "scores",
        "constraint_results",
        "critique",
        "hard_failures",
        "next_action",
        "visual_checks",
    )
    result = {field: copy.deepcopy(review.get(field)) for field in fields}
    result["rubric"] = public_rubric
    result["applicable_constraints"] = sorted(constraints)
    return result


def _finalized_root(
    manifest: dict[str, object],
    run_root: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    Path,
    Path,
]:
    if manifest.get("parent") is not None:
        raise ValueError("ordinary_root_required")
    request = manifest.get("request")
    if (
        not isinstance(request, dict)
        or request.get("workflow_template_id") != "sdxl-txt2img"
        or request.get("workflow_template_version") != 1
    ):
        raise ValueError("invalid_public_route")
    final = manifest.get("final")
    if manifest.get("state") != "finalized" or not isinstance(final, dict):
        raise ValueError("invalid_finalization")
    round_number = final.get("round_number")
    if not isinstance(round_number, int) or isinstance(round_number, bool):
        raise ValueError("invalid_finalization")
    selected, review = _selected(manifest, round_number)
    candidate = finalization_candidate(manifest, round_number)
    selected_image = selected.get("image")
    final_image = final.get("image")
    if candidate is None or not visual_checks_pass(review.get("visual_checks")):
        raise ValueError("invalid_visual_candidate")
    if (
        final.get("quality_status") != "accepted"
        or not isinstance(selected_image, dict)
        or not isinstance(final_image, dict)
        or final.get("path") != final_image.get("path")
        or final_image.get("sha256") != candidate.get("image_sha256")
        or selected_image.get("sha256") != candidate.get("image_sha256")
    ):
        raise ValueError("invalid_finalization")
    image_path = _safe_artifact(
        run_root,
        final_image,
        mime_type="image/png",
        expected_width=1280,
        expected_height=720,
    )
    preview_path = _safe_artifact(
        run_root,
        selected.get("preview"),
        mime_type="image/jpeg",
    )
    summary = {
        "run_id": candidate["run_id"],
        "round_number": candidate["round_number"],
        "image_sha256": candidate["image_sha256"],
        "bytes": image_path.stat().st_size,
        "width": final_image.get("width"),
        "height": final_image.get("height"),
        "mime_type": final_image.get("mime_type"),
        "quality_status": "accepted",
        "confirmation": candidate["confirmation"],
        "finalization_verified": True,
        "visual_checks": copy.deepcopy(review["visual_checks"]),
    }
    return summary, selected, review, image_path, preview_path


def _client_binding(
    client_session: Path,
    destination: Path,
    final: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    document, document_sha256 = _read_json_snapshot(
        client_session,
        "invalid_client_session",
    )
    if (
        validate_session(document, expected_server_version=EXPECTED_SERVER_VERSION)
        or document.get("session_purpose") != "golden_generation"
    ):
        raise ValueError("invalid_client_session")
    client = document.get("client")
    server = document.get("server")
    if not isinstance(client, dict) or not isinstance(server, dict):
        raise ValueError("invalid_client_session")
    matching_generation = any(
        isinstance(call, dict)
        and call.get("name") == "local_gpu_generate_round"
        and isinstance(call.get("result"), dict)
        and call["result"].get("run_id") == final["run_id"]
        and call["result"].get("round_number") == final["round_number"]
        and call["result"].get("image_sha256") == final["image_sha256"]
        for call in document.get("tool_calls", [])
    )
    if not matching_generation:
        raise ValueError("invalid_client_session")
    relative = Path(os.path.relpath(client_session.resolve(), destination.resolve())).as_posix()
    return (
        document,
        {
            "path": relative,
            "sha256": document_sha256,
            "client": client["name"],
            "version": client["version"],
            "session_purpose": "golden_generation",
        },
        {
            "version": server["version"],
            "wheel_sha256": server["wheel_sha256"],
        },
    )


def _public_mcp_result(
    path: Path,
    manifest: dict[str, object],
    final: dict[str, object],
) -> dict[str, object]:
    document, document_sha256 = _read_json_snapshot(path, "invalid_mcp_result")
    source_final = manifest.get("final")
    if (
        document.get("ok") is not True
        or document.get("run_id") != final["run_id"]
        or document.get("state") != "finalized"
        or document.get("final") != source_final
    ):
        raise ValueError("invalid_mcp_result")
    if "confirmation" in document and document.get("confirmation") != final["confirmation"]:
        raise ValueError("invalid_finalization")
    return {
        "schema_version": "1.0",
        "tool": "local_gpu_finalize_run",
        "source_sha256": document_sha256,
        "ok": True,
        "run_id": final["run_id"],
        "state": "finalized",
        "final": {
            "round_number": final["round_number"],
            "quality_status": "accepted",
            "image_sha256": final["image_sha256"],
        },
    }


def _artifact_record(path: Path, mime_type: str) -> dict[str, object]:
    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "mime_type": mime_type,
    }


def export_real_demo(
    run_root: Path,
    destination: Path,
    client_session: Path,
    mcp_result: Path,
    *,
    authority_path: Path,
) -> dict[str, object]:
    run_root = Path(run_root)
    destination = Path(destination)
    client_session = Path(client_session)
    mcp_result = Path(mcp_result)
    if destination.exists():
        raise ValueError("demo_destination_exists")

    rights = _public_authority(Path(authority_path))
    if not _safe_directory(run_root):
        raise ValueError("invalid_run_root")
    manifest = _read_json(run_root / "manifest.json", "invalid_run_manifest")
    if manifest.get("parent") is not None:
        raise ValueError("ordinary_root_required")
    final, selected, review, image_path, preview_path = _finalized_root(manifest, run_root)
    route = _public_route(manifest, selected)
    generation = _generation_provenance(manifest, selected)
    client_document, client_binding, installed_package = _client_binding(
        client_session,
        destination,
        final,
    )
    public_mcp_result = _public_mcp_result(mcp_result, manifest, final)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _safe_directory(destination.parent):
        raise ValueError("invalid_demo_destination_parent")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.staging-",
            dir=destination.parent,
        )
    )
    try:
        shutil.copyfile(image_path, staging / "final.png")
        shutil.copyfile(preview_path, staging / "preview.jpg")
        if sha256_file(staging / "final.png") != final["image_sha256"]:
            raise ValueError("source_artifact_sha256_mismatch")
        preview = selected.get("preview")
        if (
            not isinstance(preview, dict)
            or sha256_file(staging / "preview.jpg") != preview.get("sha256")
        ):
            raise ValueError("source_artifact_sha256_mismatch")
        validate_png(staging / "final.png", 1280, 720)

        run_public = {
            "schema_version": "2.0",
            "role": "finalized_root",
            "run_id": final["run_id"],
            "state": "finalized",
            "parent": None,
            "round_number": final["round_number"],
            "image_sha256": final["image_sha256"],
            "route": copy.deepcopy(route),
            "generation": copy.deepcopy(generation),
            "review": _sanitized_review(review, manifest),
            "final": copy.deepcopy(final),
        }
        _write_json(staging / "run-manifest.json", run_public)
        _write_json(staging / "mcp-result.json", public_mcp_result)

        transcript_lines = [
            "# Sanitized Observable Transcript",
            "",
            f"Client: `{client_binding['client']}` `{client_binding['version']}`",
            "",
            "Only observable MCP calls and sanitized structured results are retained. Prompts, hidden reasoning, account identifiers, endpoints, and machine paths are omitted.",
            "",
        ]
        for call in client_document["tool_calls"]:
            result = json.dumps(call["result"], sort_keys=True, ensure_ascii=True)
            transcript_lines.append(f"- `{call['name']}` -> `{result}`")
        transcript_lines.extend(
            [
                f"- Finalized root `{final['run_id']}` round `{final['round_number']}`: `{final['image_sha256']}`",
                "- The separate `mcp-result.json` binds the genuine finalization result by source SHA-256.",
                "",
            ]
        )
        (staging / "transcript.md").write_text(
            "\n".join(transcript_lines),
            encoding="utf-8",
            newline="\n",
        )
        readme = """# Genuine Ordinary-Route SDXL Demo

`final.png` is the original finalized PNG generated locally with SDXL 1.0 Base through ordinary `sdxl-txt2img` v1. It is copied byte-for-byte without an upscale or presentation transform.

See `showcase-manifest.json` for exact hashes, prompts, settings, route identity, review evidence, client binding, MCP finalization-result binding, public rights, and limitations.

This directory contains no model weights, backend endpoints, account data, hidden reasoning, or machine paths. The simulated protocol GIF in the parent demo directory is separate and is not model output.
"""
        (staging / "README.md").write_text(readme, encoding="utf-8", newline="\n")

        artifacts = {
            name: _artifact_record(staging / name, MIME_TYPES[name])
            for name in sorted(ARTIFACT_FILES)
        }
        mcp_binding = {
            "path": "mcp-result.json",
            "sha256": artifacts["mcp-result.json"]["sha256"],
            "source_sha256": public_mcp_result["source_sha256"],
            "tool": "local_gpu_finalize_run",
        }
        showcase = {
            "schema_version": "2.0",
            "demo_kind": "real_local_gpu_generation",
            "model_output": True,
            "installed_package": installed_package,
            "public_rights": rights,
            "route": route,
            "generation": generation,
            "final": final,
            "client_session": client_binding,
            "mcp_result": mcp_binding,
            "artifacts": artifacts,
            "known_limitations": list(KNOWN_LIMITATIONS),
        }
        _write_json(staging / "showcase-manifest.json", showcase)
        findings = validate_real_demo(staging)
        if findings:
            raise ValueError("invalid_exported_demo:" + ",".join(findings))
        if {path.name for path in staging.iterdir()} != EXPECTED_FILES:
            raise ValueError("unexpected_demo_files")
        staging.rename(destination)
        return showcase
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a sanitized genuine ordinary-route demo.")
    parser.add_argument("run_root", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("client_session", type=Path)
    parser.add_argument("mcp_result", type=Path)
    parser.add_argument("--authority", type=Path, required=True)
    args = parser.parse_args()
    manifest = export_real_demo(
        args.run_root,
        args.destination,
        args.client_session,
        args.mcp_result,
        authority_path=args.authority,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
