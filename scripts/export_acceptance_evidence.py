from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import secrets
import shutil
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from validate_acceptance_evidence import (
    EvidenceError,
    _validate_package,
    is_mock_marker,
    sha256_file,
    validate_authority,
)


ROOT = Path(__file__).resolve().parents[1]
METADATA_KEYS = {
    "brief_id",
    "host",
    "backend",
    "model",
    "environment",
    "known_limitations",
    "decision_summary",
}


class EvidenceExportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def export_run(
    run_dir: Path,
    destination: Path,
    brief_path: Path,
    metadata_path: Path,
    confirm_real: str,
    parent_evidence_path: Path | None = None,
) -> dict[str, object]:
    source_root = Path(run_dir).resolve()
    destination_path = Path(destination)
    if destination_path.exists():
        raise EvidenceExportError("evidence_destination_exists", "Evidence destination already exists.")
    if not source_root.is_dir() or _link_like(source_root):
        raise EvidenceExportError("invalid_run_directory", "Source run directory is missing or unsafe.")
    manifest = _load_object(source_root / "manifest.json", "invalid_manifest_json")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id or confirm_real != run_id:
        raise EvidenceExportError("real_run_confirmation_mismatch", "--confirm-real must exactly match the manifest run ID.")
    if manifest.get("state") != "finalized" or not isinstance(manifest.get("final"), dict):
        raise EvidenceExportError("run_not_finalized", "Only finalized runs can be exported.")
    _reject_mock_manifest(manifest)
    _validate_previews(manifest)

    briefs = _load_json(Path(brief_path), "invalid_acceptance_briefs")
    metadata = _load_object(Path(metadata_path), "invalid_observed_metadata")
    if set(metadata) != METADATA_KEYS:
        raise EvidenceExportError("invalid_observed_metadata", "Observed metadata fields are incomplete or unexpected.")
    brief_id = metadata.get("brief_id")
    if not isinstance(brief_id, str) or not brief_id:
        raise EvidenceExportError("invalid_observed_metadata", "Observed metadata requires brief_id.")
    brief = _select_brief(briefs, brief_id)
    _match_manifest_brief(manifest, brief)

    evidence_root = _find_evidence_root(destination_path)
    authority_path = evidence_root / "acceptance-authority.json"
    try:
        authority = validate_authority(authority_path, Path(brief_path))
    except EvidenceError as error:
        raise EvidenceExportError(error.code, str(error)) from error
    _match_authority(manifest, metadata, authority)

    mcp_result_source = source_root / "mcp-final-result.json"
    if not mcp_result_source.is_file() or _link_like(mcp_result_source):
        raise EvidenceExportError(
            "mcp_result_missing",
            "The original structured MCP final result must be retained beside the source manifest.",
        )
    mcp_result = _load_object(mcp_result_source, "invalid_mcp_result")
    _match_mcp_result(mcp_result, manifest)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.parent / f".{destination_path.name}.pending-{secrets.token_hex(8)}"
    if temporary.exists():
        raise EvidenceExportError("evidence_temporary_exists", "Temporary evidence destination already exists.")
    copied: dict[Path, str] = {}
    source_hashes: dict[str, str] = {}
    temporary.mkdir()
    try:
        exported_manifest = copy.deepcopy(manifest)
        _copy_manifest_artifacts(source_root, temporary, exported_manifest, copied, source_hashes)
        exported_mcp_result = copy.deepcopy(mcp_result)
        _rewrite_result_paths(source_root, temporary, exported_mcp_result, copied, source_hashes)
        _reject_absolute_strings(exported_manifest)
        _reject_absolute_strings(exported_mcp_result)

        _write_json(temporary / "brief.json", brief)
        _write_json(temporary / "manifest.json", exported_manifest)
        _write_json(temporary / "mcp-final-result.json", exported_mcp_result)
        if parent_evidence_path is not None:
            _write_parent_evidence(
                temporary,
                exported_manifest,
                Path(parent_evidence_path),
            )
        elif exported_manifest.get("parent") is not None:
            raise EvidenceExportError(
                "revision_parent_evidence_missing",
                "Child run export requires --parent-evidence.",
            )

        evidence = _build_evidence(exported_manifest, brief, metadata)
        _write_json(temporary / "evidence.json", evidence)
        parent_package = Path(parent_evidence_path).parent if parent_evidence_path is not None else None
        try:
            _validate_package(temporary, brief, authority, parent_package)
        except EvidenceError as error:
            raise EvidenceExportError(error.code, str(error)) from error
        os.replace(temporary, destination_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    export_hashes = {
        relative: sha256_file(destination_path / relative)
        for relative in sorted(source_hashes)
    }
    if export_hashes != source_hashes:
        raise EvidenceExportError("artifact_hash_mismatch", "Exported artifact bytes differ from the source run.")
    return {
        "ok": True,
        "run_id": run_id,
        "brief_id": brief_id,
        "destination": str(destination_path.resolve()),
        "artifact_count": len(export_hashes),
        "absolute_paths": 0,
        "source_hashes": source_hashes,
        "export_hashes": export_hashes,
    }


def _copy_manifest_artifacts(
    source_root: Path,
    destination: Path,
    manifest: dict[str, object],
    copied: dict[Path, str],
    source_hashes: dict[str, str],
) -> None:
    rounds = manifest.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        raise EvidenceExportError("invalid_round_evidence", "Finalized run has no successful rounds.")
    for round_value in rounds:
        if not isinstance(round_value, dict):
            raise EvidenceExportError("invalid_round_evidence", "Round metadata must be an object.")
        _copy_record(source_root, destination, round_value.get("image"), copied, source_hashes)
        if isinstance(round_value.get("preview"), dict):
            _copy_record(source_root, destination, round_value["preview"], copied, source_hashes)
        _copy_plain_path(source_root, destination, round_value.get("backend_result"), "path", copied, source_hashes)
    attempts = manifest.get("attempts")
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            if isinstance(attempt.get("image"), dict):
                _copy_record(source_root, destination, attempt["image"], copied, source_hashes)
            _copy_plain_path(source_root, destination, attempt.get("backend_result"), "path", copied, source_hashes)
    final = manifest.get("final")
    if not isinstance(final, dict):
        raise EvidenceExportError("run_not_finalized", "Final metadata is missing.")
    final_image = final.get("image")
    if not isinstance(final_image, dict):
        raise EvidenceExportError("invalid_final_evidence", "Final image metadata is missing.")
    _copy_record(source_root, destination, final_image, copied, source_hashes)
    _copy_plain_path(source_root, destination, final, "path", copied, source_hashes)
    postprocess = final.get("postprocess")
    if isinstance(postprocess, dict):
        for key in ("source", "output"):
            if isinstance(postprocess.get(key), dict):
                _copy_record(source_root, destination, postprocess[key], copied, source_hashes)
    revision = manifest.get("revision")
    if isinstance(revision, dict) and isinstance(revision.get("source_image"), dict):
        _copy_record(source_root, destination, revision["source_image"], copied, source_hashes)
    masks = manifest.get("masks")
    if isinstance(masks, list):
        for mask in masks:
            if not isinstance(mask, dict):
                raise EvidenceExportError("invalid_mask_evidence", "Mask metadata must be an object.")
            _copy_plain_path(source_root, destination, mask, "mask_path", copied, source_hashes, mask.get("mask_sha256"))
            _copy_plain_path(source_root, destination, mask, "overlay_path", copied, source_hashes)


def _copy_record(
    source_root: Path,
    destination: Path,
    record: object,
    copied: dict[Path, str],
    source_hashes: dict[str, str],
) -> None:
    if not isinstance(record, dict):
        raise EvidenceExportError("invalid_artifact_evidence", "Artifact metadata must be an object.")
    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str):
        raise EvidenceExportError("invalid_artifact_evidence", "Artifact hash is missing.")
    _copy_plain_path(source_root, destination, record, "path", copied, source_hashes, expected_hash)


def _copy_plain_path(
    source_root: Path,
    destination: Path,
    container: object,
    key: str,
    copied: dict[Path, str],
    source_hashes: dict[str, str],
    expected_hash: object = None,
) -> None:
    if not isinstance(container, dict) or key not in container:
        return
    source, relative = _source_artifact(source_root, container[key])
    if _link_like(source) or not source.is_file():
        raise EvidenceExportError("unsafe_artifact_path", "Referenced artifact is missing or link-like.")
    actual_hash = sha256_file(source)
    if expected_hash is not None and actual_hash != expected_hash:
        raise EvidenceExportError("artifact_hash_mismatch", f"Artifact hash changed: {relative}")
    prior = copied.get(source)
    if prior is not None and prior != relative:
        raise EvidenceExportError("ambiguous_artifact_path", "One source artifact maps to multiple evidence paths.")
    target = destination / Path(*PurePosixPath(relative).parts)
    if source not in copied:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied[source] = relative
        source_hashes[relative] = actual_hash
    container[key] = relative


def _source_artifact(root: Path, value: object) -> tuple[Path, str]:
    if not isinstance(value, str) or not value:
        raise EvidenceExportError("invalid_artifact_path", "Artifact path must be non-empty.")
    candidate = Path(value)
    if not candidate.is_absolute() and not PureWindowsPath(value).is_absolute():
        pure = PurePosixPath(value.replace("\\", "/"))
        if ".." in pure.parts:
            raise EvidenceExportError("artifact_path_escape", "Artifact path escapes the run directory.")
        candidate = root / Path(*pure.parts)
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise EvidenceExportError("artifact_path_escape", "Artifact path escapes the run directory.")
    relative = resolved.relative_to(root).as_posix()
    return resolved, relative


def _rewrite_result_paths(
    source_root: Path,
    destination: Path,
    value: object,
    copied: dict[Path, str],
    source_hashes: dict[str, str],
) -> None:
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if isinstance(child, str) and (key == "path" or key.endswith("_path")):
                _copy_plain_path(source_root, destination, value, key, copied, source_hashes)
            else:
                _rewrite_result_paths(source_root, destination, child, copied, source_hashes)
    elif isinstance(value, list):
        for child in value:
            _rewrite_result_paths(source_root, destination, child, copied, source_hashes)


def _write_parent_evidence(temporary: Path, child_manifest: dict[str, object], parent_evidence_path: Path) -> None:
    if parent_evidence_path.name != "evidence.json" or not parent_evidence_path.is_file():
        raise EvidenceExportError("revision_parent_evidence_missing", "Parent evidence.json is missing.")
    parent_package = parent_evidence_path.parent
    parent_manifest_path = parent_package / "manifest.json"
    parent_manifest = _load_object(parent_manifest_path, "invalid_parent_evidence")
    parent = child_manifest.get("parent")
    if not isinstance(parent, dict):
        raise EvidenceExportError("invalid_revision_lineage", "Child manifest has no parent lineage.")
    round_number = parent.get("round")
    rounds = parent_manifest.get("rounds")
    selected = next(
        (item for item in rounds if isinstance(item, dict) and item.get("round_number") == round_number),
        None,
    ) if isinstance(rounds, list) else None
    image = selected.get("image") if isinstance(selected, dict) else None
    image_hash = image.get("sha256") if isinstance(image, dict) else None
    if (
        parent.get("run_id") != parent_manifest.get("run_id")
        or parent.get("image_sha256") != image_hash
        or not isinstance(image_hash, str)
    ):
        raise EvidenceExportError("revision_parent_hash_mismatch", "Child lineage differs from retained parent evidence.")
    _write_json(temporary / "parent-evidence.json", {
        "run_id": parent_manifest["run_id"],
        "round": round_number,
        "image_sha256": image_hash,
        "manifest_sha256": sha256_file(parent_manifest_path),
        "evidence_sha256": sha256_file(parent_evidence_path),
    })


def _build_evidence(
    manifest: dict[str, object],
    brief: dict[str, object],
    metadata: dict[str, object],
) -> dict[str, object]:
    attempts = manifest.get("attempts")
    started_at = next(
        (item.get("started_at") for item in attempts if isinstance(item, dict) and isinstance(item.get("started_at"), str)),
        None,
    ) if isinstance(attempts, list) else None
    final = manifest["final"]
    if not isinstance(started_at, str) or not isinstance(final.get("finalized_at"), str):
        raise EvidenceExportError("missing_observed_timestamp", "Run start and completion timestamps must be retained.")
    return {
        "schema_version": 1,
        "evidence_class": "real-codex-mcp-run",
        "brief_id": brief["id"],
        "run_id": manifest["run_id"],
        "host": copy.deepcopy(metadata["host"]),
        "profile": brief["profile"],
        "style": brief["style"],
        "backend": copy.deepcopy(metadata["backend"]),
        "model": copy.deepcopy(metadata["model"]),
        "environment": copy.deepcopy(metadata["environment"]),
        "started_at": started_at,
        "completed_at": final["finalized_at"],
        "files": {
            "brief": "brief.json",
            "manifest": "manifest.json",
            "mcp_final_result": "mcp-final-result.json",
            "final": final["path"],
        },
        "selected_round": final["round_number"],
        "quality_status": final["quality_status"],
        "known_limitations": copy.deepcopy(metadata["known_limitations"]),
        "decision_summary": metadata["decision_summary"],
    }


def _match_authority(
    manifest: dict[str, object],
    metadata: dict[str, object],
    authority: dict[str, object],
) -> None:
    backend = metadata.get("backend")
    approved_backend = authority.get("backend")
    if not isinstance(backend, dict) or not isinstance(approved_backend, dict):
        raise EvidenceExportError("backend_authority_mismatch", "Observed backend metadata is missing.")
    for key in ("type", "implementation", "local"):
        if backend.get(key) != approved_backend.get(key):
            raise EvidenceExportError("backend_authority_mismatch", "Observed backend differs from approval.")
    model = metadata.get("model")
    if not isinstance(model, dict):
        raise EvidenceExportError("model_authority_mismatch", "Observed model metadata is missing.")
    approved = next(
        (item for item in authority["models"] if isinstance(item, dict) and item.get("id") == model.get("id")),
        None,
    )
    if approved is None:
        raise EvidenceExportError("model_authority_mismatch", "Observed model is not approved.")
    for key in ("id", "sha256", "source", "license_id", "license_url"):
        if model.get(key) != approved.get(key):
            raise EvidenceExportError("model_authority_mismatch", "Observed model facts differ from approval.")
    request = manifest.get("request")
    if not isinstance(request, dict) or request.get("model_choice") != model.get("id"):
        raise EvidenceExportError("model_authority_mismatch", "Manifest model differs from observed metadata.")


def _reject_mock_manifest(manifest: dict[str, object]) -> None:
    request = manifest.get("request")
    values: list[object] = []
    if isinstance(request, dict):
        values.extend((request.get("backend"), request.get("model_choice")))
    for collection_name in ("rounds", "attempts"):
        collection = manifest.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            values.append(item.get("backend"))
            result = item.get("backend_result")
            if isinstance(result, dict):
                values.extend((result.get("backend"), result.get("model")))
    if any(isinstance(value, str) and is_mock_marker(value) for value in values):
        raise EvidenceExportError("mock_evidence_forbidden", "Mock/test/fixture backend markers cannot be exported.")


def _validate_previews(manifest: dict[str, object]) -> None:
    global_warnings = manifest.get("warnings") if isinstance(manifest.get("warnings"), list) else []
    rounds = manifest.get("rounds")
    if not isinstance(rounds, list):
        raise EvidenceExportError("invalid_round_evidence", "Manifest rounds are missing.")
    for round_value in rounds:
        if not isinstance(round_value, dict):
            raise EvidenceExportError("invalid_round_evidence", "Round metadata must be an object.")
        if isinstance(round_value.get("preview"), dict):
            continue
        warnings = list(global_warnings)
        if isinstance(round_value.get("warnings"), list):
            warnings.extend(round_value["warnings"])
        if not any(isinstance(item, str) and item.startswith("preview_unavailable") for item in warnings):
            raise EvidenceExportError("preview_evidence_missing", "A missing preview requires a retained warning.")


def _match_mcp_result(result: dict[str, object], manifest: dict[str, object]) -> None:
    final = result.get("final")
    manifest_final = manifest.get("final")
    if (
        result.get("run_id") != manifest.get("run_id")
        or result.get("state") != "finalized"
        or not isinstance(final, dict)
        or not isinstance(manifest_final, dict)
        or final.get("round_number") != manifest_final.get("round_number")
        or final.get("quality_status") != manifest_final.get("quality_status")
    ):
        raise EvidenceExportError("mcp_result_mismatch", "Original MCP final result differs from the manifest.")


def _match_manifest_brief(manifest: dict[str, object], brief: dict[str, object]) -> None:
    request = manifest.get("request")
    if not isinstance(request, dict):
        raise EvidenceExportError("brief_evidence_mismatch", "Manifest request is missing.")
    for key in ("profile", "style", "subtype"):
        if request.get(key) != brief.get(key):
            raise EvidenceExportError("brief_evidence_mismatch", f"Manifest {key} differs from the fixed brief.")


def _select_brief(value: object, brief_id: str) -> dict[str, object]:
    if isinstance(value, dict):
        candidates = [value]
    elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
        candidates = value
    else:
        raise EvidenceExportError("invalid_acceptance_briefs", "Brief input must be one object or an array.")
    matches = [item for item in candidates if item.get("id") == brief_id]
    if len(matches) != 1:
        raise EvidenceExportError("brief_evidence_mismatch", "Observed brief ID is not unique in the fixture.")
    return copy.deepcopy(matches[0])


def _find_evidence_root(destination: Path) -> Path:
    for ancestor in destination.parents:
        if (ancestor / "acceptance-authority.json").is_file():
            return ancestor
    raise EvidenceExportError("missing_acceptance_authority", "No acceptance-authority.json exists above destination.")


def _reject_absolute_strings(value: object, key: str | None = None) -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            _reject_absolute_strings(child, child_key)
    elif isinstance(value, list):
        for child in value:
            _reject_absolute_strings(child, key)
    elif isinstance(value, str) and (key == "path" or (isinstance(key, str) and key.endswith("_path"))):
        if Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
            raise EvidenceExportError("absolute_evidence_path", "Sanitized evidence still contains an absolute path.")


def _load_json(path: Path, code: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceExportError(code, f"Cannot read JSON input: {path.name}") from error


def _load_object(path: Path, code: str) -> dict[str, object]:
    value = _load_json(path, code)
    if not isinstance(value, dict):
        raise EvidenceExportError(code, f"JSON input must be an object: {path.name}")
    return value


def _write_json(path: Path, value: object) -> None:
    try:
        path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        raise EvidenceExportError("evidence_write_failed", f"Cannot write evidence JSON: {path.name}") from error


def _link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--confirm-real", required=True)
    parser.add_argument("--parent-evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        result = export_run(
            args.run_dir,
            args.destination,
            args.brief,
            args.metadata,
            args.confirm_real,
            args.parent_evidence,
        )
    except EvidenceExportError as error:
        print(json.dumps({"ok": False, "code": error.code, "message": str(error)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
