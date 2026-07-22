#!/usr/bin/env python
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from build_showcase import build_showcase
from local_gpu_imagegen.artifacts import sha256_file, validate_png
from local_gpu_imagegen.visual_review import finalization_candidate, visual_checks_pass
from validate_client_sessions import validate_session
from validate_real_demo import (
    ARTIFACT_FILES,
    BUNDLE_SHA256,
    EXPECTED_FILES,
    EXPECTED_PRESERVE,
    EXPECTED_RIGHTS,
    EXPECTED_ROUTE,
    EXPECTED_SERVER_VERSION,
    MIME_TYPES,
    MODEL_ID,
    MODEL_SHA256,
    WORKFLOW_SHA256,
    validate_real_demo,
)


ShowcaseBuilder = Callable[[Path, Path, Path], None]
KNOWN_LIMITATIONS = [
    "This showcase records one observed local Windows and ComfyUI configuration.",
    "SDXL 1.0 Base is used without an SDXL refiner or automatic upscale pass.",
    "The control-plane evidence does not prove that the underlying model will satisfy every visual brief.",
    "The complete nine-root plus three-revision public acceptance matrix remains outside this preview.",
]


def _read_json(path: Path, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _selected(manifest: dict[str, object], round_number: int) -> tuple[dict[str, object], dict[str, object]]:
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
    path = (root / relative).resolve()
    if path.parent != root or not path.is_file() or path.is_symlink():
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
        if len(data) > 1024 * 1024 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
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


def _public_route(manifest: dict[str, object], selected: dict[str, object]) -> dict[str, object]:
    request = manifest.get("request")
    if not isinstance(request, dict):
        raise ValueError("invalid_public_route")
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
        "width": backend_result.get("width"),
        "height": backend_result.get("height"),
        "steps": backend_result.get("steps"),
        "guidance_scale": backend_result.get("guidance_scale"),
        "sampler": backend_result.get("sampler"),
        "scheduler": backend_result.get("scheduler"),
        "upscale_policy": request.get("upscale_policy"),
    }
    if observed != EXPECTED_ROUTE:
        raise ValueError("invalid_public_route")
    return copy.deepcopy(observed)


def _candidate_summary(
    manifest: dict[str, object],
    round_number: int,
    review: dict[str, object],
) -> dict[str, object]:
    candidate = finalization_candidate(manifest, round_number)
    if candidate is None or not visual_checks_pass(review.get("visual_checks")):
        raise ValueError("invalid_visual_candidate")
    selected, _ = _selected(manifest, round_number)
    seed = selected.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("invalid_visual_candidate")
    return {
        "run_id": candidate["run_id"],
        "round_number": candidate["round_number"],
        "image_sha256": candidate["image_sha256"],
        "seed": seed,
        "quality_status": candidate["quality_status"],
        "confirmation": candidate["confirmation"],
        "visual_checks": copy.deepcopy(review["visual_checks"]),
    }


def _revision_summary(
    manifest: dict[str, object],
    round_number: int,
    review: dict[str, object],
    parent_summary: dict[str, object],
) -> dict[str, object]:
    candidate = _candidate_summary(manifest, round_number, review)
    parent = manifest.get("parent")
    expected_parent = {
        "run_id": parent_summary["run_id"],
        "round": parent_summary["round_number"],
        "image_sha256": parent_summary["image_sha256"],
    }
    revision = manifest.get("revision")
    if not isinstance(revision, dict) or parent != expected_parent:
        raise ValueError("invalid_revision_lineage")
    source_image = revision.get("source_image")
    if not isinstance(source_image, dict) or source_image.get("sha256") != parent_summary["image_sha256"]:
        raise ValueError("invalid_revision_lineage")
    contract = revision.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("invalid_revision_contract")
    preserve = contract.get("preserve")
    change = contract.get("change")
    if not isinstance(preserve, list) or not isinstance(change, list):
        raise ValueError("invalid_revision_contract")
    by_target = {
        item.get("target"): item
        for item in preserve
        if isinstance(item, dict) and isinstance(item.get("target"), str)
    }
    canonical_preserve = [by_target.get(item["target"]) for item in EXPECTED_PRESERVE]
    if canonical_preserve != EXPECTED_PRESERVE or change != ["palette_and_lighting"]:
        raise ValueError("invalid_revision_contract")
    preservation = review.get("preservation_results")
    if not isinstance(preservation, list):
        raise ValueError("preservation_not_passed")
    preservation_by_target = {
        item.get("target"): item
        for item in preservation
        if isinstance(item, dict) and isinstance(item.get("target"), str)
    }
    canonical_results = [
        preservation_by_target.get(item["target"])
        for item in EXPECTED_PRESERVE
    ]
    if any(
        not isinstance(item, dict) or item.get("status") != "preserved"
        for item in canonical_results
    ):
        raise ValueError("preservation_not_passed")
    final = manifest.get("final")
    if (
        manifest.get("state") != "finalized"
        or not isinstance(final, dict)
        or final.get("round_number") != round_number
        or final.get("quality_status") != "accepted"
        or not isinstance(final.get("image"), dict)
        or final["image"].get("sha256") != candidate["image_sha256"]
    ):
        raise ValueError("invalid_revision_finalization")
    return {
        **candidate,
        "quality_status": "accepted",
        "parent": expected_parent,
        "edit_mode": revision.get("edit_mode"),
        "preserve": copy.deepcopy(EXPECTED_PRESERVE),
        "change": ["palette_and_lighting"],
        "finalization_verified": True,
        "preservation_results": copy.deepcopy(canonical_results),
    }


def _artifact_record(path: Path, mime_type: str) -> dict[str, object]:
    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "mime_type": mime_type,
    }


def _sanitized_review(review: dict[str, object]) -> dict[str, object]:
    fields = ("round_number", "reviewed_at", "scores", "hard_failures", "next_action", "visual_checks")
    return {field: copy.deepcopy(review.get(field)) for field in fields}


def export_real_demo(
    root_run: Path,
    child_run: Path,
    destination: Path,
    client_session: Path,
    *,
    authority_path: Path,
    showcase_builder: ShowcaseBuilder = build_showcase,
) -> dict[str, object]:
    root_run = Path(root_run)
    child_run = Path(child_run)
    destination = Path(destination)
    client_session = Path(client_session)
    if destination.exists():
        raise ValueError("demo_destination_exists")

    rights = _public_authority(Path(authority_path))
    root_manifest = _read_json(root_run / "manifest.json", "invalid_root_manifest")
    child_manifest = _read_json(child_run / "manifest.json", "invalid_revision_manifest")
    parent = child_manifest.get("parent")
    if not isinstance(parent, dict) or parent.get("run_id") != root_manifest.get("run_id"):
        raise ValueError("invalid_revision_lineage")
    parent_round = parent.get("round")
    if not isinstance(parent_round, int) or isinstance(parent_round, bool):
        raise ValueError("invalid_revision_lineage")
    root_selected, root_review = _selected(root_manifest, parent_round)
    root_summary = _candidate_summary(root_manifest, parent_round, root_review)
    if parent.get("image_sha256") != root_summary["image_sha256"]:
        raise ValueError("invalid_revision_lineage")

    child_final = child_manifest.get("final")
    child_round = child_final.get("round_number") if isinstance(child_final, dict) else None
    if not isinstance(child_round, int) or isinstance(child_round, bool):
        raise ValueError("invalid_revision_finalization")
    child_selected, child_review = _selected(child_manifest, child_round)
    revision_summary = _revision_summary(
        child_manifest,
        child_round,
        child_review,
        root_summary,
    )
    if revision_summary["seed"] != root_summary["seed"]:
        raise ValueError("seed_not_preserved")
    route = _public_route(root_manifest, root_selected)
    if _public_route(child_manifest, child_selected) != route:
        raise ValueError("revision_route_changed")

    root_image = _safe_artifact(
        root_run,
        root_selected.get("image"),
        mime_type="image/png",
        expected_width=1280,
        expected_height=720,
    )
    root_preview = _safe_artifact(
        root_run,
        root_selected.get("preview"),
        mime_type="image/jpeg",
    )
    final_image = child_final.get("image") if isinstance(child_final, dict) else None
    child_image = _safe_artifact(
        child_run,
        final_image,
        mime_type="image/png",
        expected_width=1280,
        expected_height=720,
    )
    child_preview = _safe_artifact(
        child_run,
        child_selected.get("preview"),
        mime_type="image/jpeg",
    )

    client_document = _read_json(client_session, "invalid_client_session")
    if validate_session(client_document, expected_server_version=EXPECTED_SERVER_VERSION):
        raise ValueError("invalid_client_session")
    client = client_document.get("client")
    if not isinstance(client, dict):
        raise ValueError("invalid_client_session")
    relative_client = Path(os.path.relpath(client_session.resolve(), destination.resolve())).as_posix()

    destination.mkdir(parents=True)
    try:
        shutil.copyfile(root_image, destination / "before.png")
        shutil.copyfile(child_image, destination / "after.png")
        shutil.copyfile(root_preview, destination / "before-preview.jpg")
        shutil.copyfile(child_preview, destination / "after-preview.jpg")

        root_public = {
            "schema_version": "1.0",
            "role": "root",
            "run_id": root_summary["run_id"],
            "state": "reviewed_candidate",
            "round_number": root_summary["round_number"],
            "image_sha256": root_summary["image_sha256"],
            "seed": root_summary["seed"],
            "confirmation": root_summary["confirmation"],
            "route": copy.deepcopy(route),
            "review": _sanitized_review(root_review),
        }
        revision_public = {
            "schema_version": "1.0",
            "role": "revision",
            "run_id": revision_summary["run_id"],
            "state": "finalized",
            "parent": copy.deepcopy(revision_summary["parent"]),
            "round_number": revision_summary["round_number"],
            "image_sha256": revision_summary["image_sha256"],
            "seed": revision_summary["seed"],
            "confirmation": revision_summary["confirmation"],
            "edit_mode": revision_summary["edit_mode"],
            "preserve": copy.deepcopy(revision_summary["preserve"]),
            "change": copy.deepcopy(revision_summary["change"]),
            "route": copy.deepcopy(route),
            "review": _sanitized_review(child_review),
        }
        _write_json(destination / "root-manifest.json", root_public)
        _write_json(destination / "revision-manifest.json", revision_public)

        transcript_lines = [
            "# Sanitized Observable Transcript",
            "",
            f"Client: `{client['name']}` `{client['version']}`",
            "",
            "Only observable MCP calls and sanitized structured results are retained. Prompts, hidden reasoning, account identifiers, endpoints, and machine paths are omitted.",
            "",
        ]
        for call in client_document["tool_calls"]:
            result = json.dumps(call["result"], sort_keys=True, ensure_ascii=True)
            transcript_lines.append(f"- `{call['name']}` -> `{result}`")
        transcript_lines.extend(
            [
                f"- Root candidate `{root_summary['run_id']}` round `{root_summary['round_number']}`: `{root_summary['image_sha256']}`",
                f"- Finalized revision `{revision_summary['run_id']}` round `{revision_summary['round_number']}`: `{revision_summary['image_sha256']}`",
                "",
            ]
        )
        (destination / "transcript.md").write_text(
            "\n".join(transcript_lines), encoding="utf-8", newline="\n"
        )
        readme = """# Genuine SDXL Hot-Revision Demo

`before.png` is the reviewed root candidate. `after.png` is an immutable prompt-refine child finalized through the byte-bound confirmation contract. Both files were generated locally through the reviewed SDXL 1.0 Base ComfyUI route.

The revision preserves composition, the primary telescope motif, and the left copy-safe area while changing only palette and lighting. See `showcase-manifest.json` for exact hashes, route identity, settings, lineage, review evidence, client evidence, and limitations.

This directory contains no model weights, prompts, backend endpoints, account data, hidden reasoning, or machine paths. The simulated protocol animation in the parent demo directory is separate and is not model output.
"""
        (destination / "README.md").write_text(readme, encoding="utf-8", newline="\n")
        showcase_builder(
            destination / "before.png",
            destination / "after.png",
            destination / "showcase.gif",
        )

        artifacts = {
            name: _artifact_record(destination / name, MIME_TYPES[name])
            for name in sorted(ARTIFACT_FILES)
        }
        manifest = {
            "schema_version": "1.0",
            "demo_kind": "real_local_gpu_hot_revision",
            "model_output": True,
            "public_rights": rights,
            "route": route,
            "root": root_summary,
            "revision": revision_summary,
            "client_session": {
                "path": relative_client,
                "sha256": sha256_file(client_session),
                "client": client["name"],
                "version": client["version"],
            },
            "artifacts": artifacts,
            "known_limitations": list(KNOWN_LIMITATIONS),
        }
        _write_json(destination / "showcase-manifest.json", manifest)
        findings = validate_real_demo(destination)
        if findings:
            raise ValueError("invalid_exported_demo:" + ",".join(findings))
        if {path.name for path in destination.iterdir() if path.is_file()} != EXPECTED_FILES:
            raise ValueError("unexpected_demo_files")
        return manifest
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a sanitized genuine hot-revision demo.")
    parser.add_argument("root_run", type=Path)
    parser.add_argument("child_run", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("client_session", type=Path)
    parser.add_argument("--authority", type=Path, required=True)
    args = parser.parse_args()
    manifest = export_real_demo(
        args.root_run,
        args.child_run,
        args.destination,
        args.client_session,
        authority_path=args.authority,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
