from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_KEYS = {
    "schema_version",
    "evidence_class",
    "brief_id",
    "run_id",
    "host",
    "profile",
    "style",
    "backend",
    "model",
    "environment",
    "started_at",
    "completed_at",
    "files",
    "selected_round",
    "quality_status",
    "known_limitations",
    "decision_summary",
}
CORE_PACKAGE_FILES = {"evidence.json", "brief.json", "manifest.json", "mcp-final-result.json"}


class EvidenceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise EvidenceError("evidence_file_unreadable", f"Cannot read evidence file: {path.name}") from error
    return digest.hexdigest()


def resolve_relative(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or _is_absolute_path(value):
        raise EvidenceError("absolute_evidence_path", "Evidence paths must be non-empty and relative.")
    pure = PurePosixPath(value.replace("\\", "/"))
    if ".." in pure.parts:
        raise EvidenceError("evidence_path_escape", "Evidence path escapes its package.")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*pure.parts)).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise EvidenceError("evidence_path_escape", "Evidence path escapes its package.")
    return resolved


def is_mock_marker(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in ("mock", "fake", "fixture", "synthetic-test"))


def validate_evidence(root: Path, briefs_path: Path, strict: bool = False) -> dict[str, object]:
    evidence_root = Path(root)
    briefs_file = Path(briefs_path)
    briefs = _load_briefs(briefs_file)
    briefs_by_id = {str(item["id"]): item for item in briefs}
    revision_ids = {brief_id for brief_id, item in briefs_by_id.items() if "revision" in item}
    _reject_links(evidence_root)

    run_ids = _package_ids(evidence_root / "runs")
    child_ids = _package_ids(evidence_root / "revisions")
    unknown = (run_ids | child_ids) - set(briefs_by_id)
    if unknown:
        raise EvidenceError("unknown_brief_evidence", f"Evidence uses unknown brief IDs: {', '.join(sorted(unknown))}")
    unexpected_revisions = child_ids - revision_ids
    if unexpected_revisions:
        raise EvidenceError("unexpected_revision_evidence", "Only fixture-declared revisions may be retained.")

    authority_path = evidence_root / "acceptance-authority.json"
    authority: dict[str, object] | None = None
    if authority_path.is_file():
        authority = validate_authority(authority_path, briefs_file)
    elif strict or run_ids or child_ids:
        raise EvidenceError("missing_acceptance_authority", "Retained real evidence requires approved authority.")

    if strict:
        missing_runs = set(briefs_by_id) - run_ids
        if missing_runs:
            raise EvidenceError("missing_run_evidence", f"Missing real run evidence: {', '.join(sorted(missing_runs))}")
        missing_revisions = revision_ids - child_ids
        if missing_revisions:
            raise EvidenceError(
                "missing_revision_evidence",
                f"Missing real revision evidence: {', '.join(sorted(missing_revisions))}",
            )

    profiles: set[str] = set()
    for brief_id in sorted(run_ids):
        package = evidence_root / "runs" / brief_id
        result = _validate_package(package, briefs_by_id[brief_id], authority, None)
        profiles.add(str(result["profile"]))
    for brief_id in sorted(child_ids):
        parent_package = evidence_root / "runs" / brief_id
        if not parent_package.is_dir():
            raise EvidenceError("revision_parent_evidence_missing", f"Revision {brief_id} has no retained parent package.")
        _validate_package(evidence_root / "revisions" / brief_id, briefs_by_id[brief_id], authority, parent_package)

    release_ready = (
        authority is not None
        and run_ids == set(briefs_by_id)
        and child_ids == revision_ids
    )
    return {
        "ok": True,
        "strict": strict,
        "authority_status": "approved" if authority is not None else "missing",
        "run_count": len(run_ids),
        "revision_count": len(child_ids),
        "profiles": len(profiles),
        "run_ids": sorted(run_ids),
        "revision_ids": sorted(child_ids),
        "release_ready": release_ready,
    }


def validate_authority(path: Path, briefs_path: Path) -> dict[str, object]:
    authority = _load_object(path, "invalid_acceptance_authority")
    if authority.get("schema_version") != 1:
        raise EvidenceError("invalid_acceptance_authority", "Authority schema version is invalid.")
    if authority.get("status") != "approved":
        raise EvidenceError("acceptance_authority_unapproved", "The authority record is not approved.")
    required = {
        "schema_version",
        "status",
        "approved_at",
        "briefs_sha256",
        "backend",
        "models",
        "repository_license",
        "copyright_holder",
        "installation_or_download",
    }
    if set(authority) != required:
        raise EvidenceError("invalid_acceptance_authority", "Authority fields or schema version are invalid.")
    _require_timestamp(authority.get("approved_at"), "invalid_acceptance_authority")
    if authority.get("briefs_sha256") != sha256_file(briefs_path):
        raise EvidenceError("acceptance_briefs_changed", "Acceptance briefs differ from the approved hash.")
    backend = authority.get("backend")
    if (
        not isinstance(backend, dict)
        or backend.get("type") not in {"webui", "diffusers"}
        or not _nonempty(backend.get("implementation"))
        or backend.get("local") is not True
    ):
        raise EvidenceError("invalid_acceptance_authority", "Approved backend metadata is incomplete.")
    models = authority.get("models")
    if not isinstance(models, list) or not models:
        raise EvidenceError("invalid_acceptance_authority", "Authority requires at least one approved model.")
    seen_models: set[str] = set()
    for model in models:
        if not isinstance(model, dict):
            raise EvidenceError("invalid_acceptance_authority", "Approved model records must be objects.")
        required_model = {
            "id", "source", "sha256", "license_id", "license_url",
            "output_redistribution_status", "expected_storage", "use_approved", "download_approved",
        }
        if set(model) != required_model:
            raise EvidenceError("invalid_acceptance_authority", "Approved model fields are incomplete.")
        model_id = model.get("id")
        if not _nonempty(model_id) or model_id in seen_models or is_mock_marker(str(model_id)):
            raise EvidenceError("invalid_acceptance_authority", "Approved model IDs must be unique and real.")
        seen_models.add(str(model_id))
        if not all(_nonempty(model.get(key)) for key in ("source", "license_id", "license_url", "expected_storage")):
            raise EvidenceError("invalid_acceptance_authority", "Approved model source and license facts are required.")
        if not _valid_sha(model.get("sha256")) or model.get("use_approved") is not True:
            raise EvidenceError("invalid_acceptance_authority", "Approved model hash or use authority is invalid.")
        if model.get("output_redistribution_status") != "approved":
            raise EvidenceError("model_output_redistribution_unapproved", "Public evidence requires output redistribution approval.")
        if type(model.get("download_approved")) is not bool:
            raise EvidenceError("invalid_acceptance_authority", "Model download approval must be explicit.")
    if authority.get("repository_license") not in {"MIT", "Apache-2.0"}:
        raise EvidenceError("invalid_acceptance_authority", "Repository license must be explicitly approved.")
    if not _nonempty(authority.get("copyright_holder")):
        raise EvidenceError("invalid_acceptance_authority", "Copyright holder is required.")
    install = authority.get("installation_or_download")
    if (
        not isinstance(install, dict)
        or set(install) != {"approved", "items"}
        or type(install.get("approved")) is not bool
        or not isinstance(install.get("items"), list)
        or not all(_nonempty(item) for item in install["items"])
    ):
        raise EvidenceError("invalid_acceptance_authority", "Install/download authority is invalid.")
    return authority


def _validate_package(
    package: Path,
    expected_brief: dict[str, object],
    authority: dict[str, object] | None,
    parent_package: Path | None,
) -> dict[str, object]:
    if authority is None:
        raise EvidenceError("missing_acceptance_authority", "Evidence packages require approved authority.")
    _reject_links(package)
    for filename in CORE_PACKAGE_FILES:
        if not (package / filename).is_file():
            raise EvidenceError("evidence_file_missing", f"Evidence package is missing {filename}.")
    evidence = _load_object(package / "evidence.json", "invalid_evidence_json")
    manifest = _load_object(package / "manifest.json", "invalid_manifest_json")
    brief = _load_object(package / "brief.json", "invalid_brief_json")
    mcp_result = _load_object(package / "mcp-final-result.json", "invalid_mcp_result")
    if brief != expected_brief:
        raise EvidenceError("brief_evidence_mismatch", "Retained brief differs from the fixed acceptance fixture.")
    if set(evidence) != EVIDENCE_KEYS or evidence.get("schema_version") != 1:
        raise EvidenceError("invalid_evidence_shape", "Evidence metadata has unexpected fields.")
    if evidence.get("evidence_class") != "real-codex-mcp-run":
        raise EvidenceError("invalid_evidence_class", "Evidence must identify a real Codex MCP run.")
    if evidence.get("quality_status") != "accepted":
        raise EvidenceError("evidence_not_accepted", "Retained evidence must be accepted.")
    if evidence.get("brief_id") != expected_brief.get("id"):
        raise EvidenceError("brief_evidence_mismatch", "Evidence brief ID is incorrect.")
    if evidence.get("profile") != expected_brief.get("profile") or evidence.get("style") != expected_brief.get("style"):
        raise EvidenceError("profile_evidence_mismatch", "Evidence Profile or style differs from the fixture.")
    _require_timestamp(evidence.get("started_at"), "invalid_evidence_timestamp")
    _require_timestamp(evidence.get("completed_at"), "invalid_evidence_timestamp")
    if not _nonempty(evidence.get("decision_summary")):
        raise EvidenceError("invalid_evidence_summary", "Decision summary must be concise and non-empty.")
    limitations = evidence.get("known_limitations")
    if not isinstance(limitations, list) or not limitations or not all(_nonempty(item) for item in limitations):
        raise EvidenceError("invalid_evidence_limitations", "Known limitations must be recorded.")
    _validate_host_environment(evidence)
    _validate_backend_model(evidence, authority)

    files = evidence.get("files")
    if not isinstance(files, dict) or set(files) != {"brief", "manifest", "mcp_final_result", "final"}:
        raise EvidenceError("invalid_evidence_files", "Evidence files mapping is invalid.")
    expected_core = {
        "brief": "brief.json",
        "manifest": "manifest.json",
        "mcp_final_result": "mcp-final-result.json",
    }
    for key, expected in expected_core.items():
        if files.get(key) != expected:
            raise EvidenceError("invalid_evidence_files", "Core evidence filenames are fixed.")
    referenced_files = set(CORE_PACKAGE_FILES)
    for value in files.values():
        path = resolve_relative(package, value)
        if not path.is_file():
            raise EvidenceError("evidence_file_missing", f"Referenced evidence file is missing: {value}")
        referenced_files.add(path.relative_to(package.resolve()).as_posix())

    run_id = evidence.get("run_id")
    if not _nonempty(run_id) or manifest.get("run_id") != run_id or mcp_result.get("run_id") != run_id:
        raise EvidenceError("mcp_result_mismatch", "Evidence, manifest, and MCP result run IDs must match.")
    if manifest.get("state") != "finalized" or mcp_result.get("state") != "finalized":
        raise EvidenceError("run_not_finalized", "Retained evidence must come from a finalized run.")
    request = manifest.get("request")
    if not isinstance(request, dict):
        raise EvidenceError("invalid_manifest", "Manifest request is missing.")
    for key in ("profile", "style", "subtype"):
        if request.get(key) != expected_brief.get(key):
            raise EvidenceError("profile_evidence_mismatch", f"Manifest {key} differs from the fixture.")
    if request.get("model_choice") != evidence["model"]["id"]:
        raise EvidenceError("model_evidence_mismatch", "Manifest model choice differs from evidence metadata.")
    if is_mock_marker(str(request.get("backend", ""))):
        raise EvidenceError("mock_evidence_forbidden", "Mock backend markers are forbidden in real evidence.")

    rounds = manifest.get("rounds")
    if not isinstance(rounds, list) or not 1 <= len(rounds) <= 3:
        raise EvidenceError("invalid_round_evidence", "Evidence must retain one to three successful rounds.")
    round_numbers: set[int] = set()
    for round_value in rounds:
        if not isinstance(round_value, dict):
            raise EvidenceError("invalid_round_evidence", "Round evidence must be an object.")
        number = round_value.get("round_number")
        if type(number) is not int or not 1 <= number <= 3 or number in round_numbers:
            raise EvidenceError("invalid_round_evidence", "Round numbers must be unique integers from one to three.")
        round_numbers.add(number)
        if round_value.get("status") != "generated":
            raise EvidenceError("invalid_round_evidence", "Only successful generated rounds belong in the matrix.")
        if is_mock_marker(str(round_value.get("backend", ""))):
            raise EvidenceError("mock_evidence_forbidden", "Mock backend markers are forbidden in real evidence.")
        backend_result = round_value.get("backend_result")
        if isinstance(backend_result, dict):
            for key in ("backend", "model"):
                if is_mock_marker(str(backend_result.get(key, ""))):
                    raise EvidenceError("mock_evidence_forbidden", "Mock backend markers are forbidden in real evidence.")
            if "path" in backend_result:
                referenced_files.add(_relative_file(package, backend_result["path"]))
        referenced_files.add(_validate_artifact(package, round_value.get("image"), "image/png"))
        preview = round_value.get("preview")
        if isinstance(preview, dict):
            referenced_files.add(_validate_artifact(package, preview, "image/jpeg"))
        elif not _has_preview_warning(manifest, round_value):
            raise EvidenceError("preview_evidence_missing", "Every round needs a preview or preview_unavailable warning.")

    selected_round = evidence.get("selected_round")
    if type(selected_round) is not int or selected_round not in round_numbers:
        raise EvidenceError("invalid_selected_round", "Selected round is not retained.")
    reviews = manifest.get("reviews")
    if not isinstance(reviews, list):
        raise EvidenceError("invalid_review_evidence", "Manifest reviews are missing.")
    review = next((item for item in reviews if isinstance(item, dict) and item.get("round_number") == selected_round), None)
    if review is None or review.get("hard_failures") != []:
        raise EvidenceError("invalid_review_evidence", "Selected round requires a clean retained review.")
    final = manifest.get("final")
    if (
        not isinstance(final, dict)
        or final.get("round_number") != selected_round
        or final.get("quality_status") != "accepted"
    ):
        raise EvidenceError("invalid_final_evidence", "Final selection must reference an accepted reviewed round.")
    final_path = _validate_artifact(package, final.get("image"), "image/png")
    referenced_files.add(final_path)
    if _relative_file(package, final.get("path")) != final_path or _relative_file(package, files.get("final")) != final_path:
        raise EvidenceError("invalid_final_evidence", "Final path references are inconsistent.")
    mcp_final = mcp_result.get("final")
    if not isinstance(mcp_final, dict) or mcp_final.get("quality_status") != "accepted":
        raise EvidenceError("mcp_result_mismatch", "MCP final result does not retain acceptance.")

    if parent_package is not None:
        referenced_files.add("parent-evidence.json")
        _validate_revision(package, manifest, review, parent_package, referenced_files)
    elif manifest.get("parent") is not None:
        raise EvidenceError("unexpected_revision_lineage", "Root run evidence cannot contain child lineage.")

    actual_files = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file()
    }
    if actual_files != referenced_files:
        raise EvidenceError("unexpected_evidence_file", "Evidence package contains missing or unreferenced files.")
    return {"profile": evidence["profile"], "run_id": run_id}


def _validate_revision(
    package: Path,
    manifest: dict[str, object],
    review: dict[str, object],
    parent_package: Path,
    referenced_files: set[str],
) -> None:
    parent_record = _load_object(package / "parent-evidence.json", "invalid_parent_evidence")
    parent_manifest_path = parent_package / "manifest.json"
    parent_evidence_path = parent_package / "evidence.json"
    parent_manifest = _load_object(parent_manifest_path, "invalid_parent_evidence")
    parent = manifest.get("parent")
    revision = manifest.get("revision")
    if not isinstance(parent, dict) or not isinstance(revision, dict):
        raise EvidenceError("invalid_revision_lineage", "Child manifest lineage is incomplete.")
    parent_round = parent_record.get("round")
    rounds = parent_manifest.get("rounds")
    if not isinstance(rounds, list):
        raise EvidenceError("invalid_parent_evidence", "Parent rounds are missing.")
    selected = next((item for item in rounds if isinstance(item, dict) and item.get("round_number") == parent_round), None)
    image = selected.get("image") if isinstance(selected, dict) else None
    expected_image_hash = image.get("sha256") if isinstance(image, dict) else None
    if (
        parent_record.get("run_id") != parent_manifest.get("run_id")
        or parent.get("run_id") != parent_manifest.get("run_id")
        or parent.get("round") != parent_round
        or not _valid_sha(expected_image_hash)
        or parent_record.get("image_sha256") != expected_image_hash
        or parent.get("image_sha256") != expected_image_hash
    ):
        raise EvidenceError("revision_parent_hash_mismatch", "Revision parent image lineage does not match.")
    if (
        parent_record.get("manifest_sha256") != sha256_file(parent_manifest_path)
        or parent_record.get("evidence_sha256") != sha256_file(parent_evidence_path)
    ):
        raise EvidenceError("revision_parent_hash_mismatch", "Revision parent package hashes do not match.")
    contract = revision.get("contract")
    preserve = contract.get("preserve") if isinstance(contract, dict) else None
    change = contract.get("change") if isinstance(contract, dict) else None
    if (
        not isinstance(preserve, list)
        or len(preserve) != 2
        or not all(isinstance(item, dict) and item.get("strength") == "hard" and _nonempty(item.get("target")) for item in preserve)
        or not isinstance(change, list)
        or len(change) != 1
        or not _nonempty(change[0])
    ):
        raise EvidenceError("invalid_revision_contract", "Revision evidence requires two hard preserves and one change.")
    targets = [str(item["target"]) for item in preserve]
    results = review.get("preservation_results")
    if (
        not isinstance(results, list)
        or {item.get("target") for item in results if isinstance(item, dict)} != set(targets)
        or any(item.get("status") != "preserved" or not _nonempty(item.get("observation")) for item in results if isinstance(item, dict))
    ):
        raise EvidenceError("invalid_preservation_evidence", "Every hard preserve target must be observed as preserved.")
    if revision.get("edit_mode") == "inpaint":
        masks = manifest.get("masks")
        if not isinstance(masks, list) or not masks:
            raise EvidenceError("missing_mask_evidence", "Inpaint evidence requires a confirmed retained mask.")
        mask = next((item for item in masks if isinstance(item, dict) and item.get("confirmed") is True), None)
        if mask is None or not _nonempty(mask.get("confirmed_at")) or "automatic_segmentation" in json.dumps(mask):
            raise EvidenceError("invalid_mask_evidence", "Inpaint mask confirmation evidence is invalid.")
        if mask.get("source_image_sha256") != expected_image_hash or not _valid_sha(mask.get("mask_sha256")):
            raise EvidenceError("invalid_mask_evidence", "Mask source or content hash is invalid.")
        mask_path = _relative_file(package, mask.get("mask_path"))
        overlay_path = _relative_file(package, mask.get("overlay_path"))
        if sha256_file(package / mask_path) != mask.get("mask_sha256"):
            raise EvidenceError("artifact_hash_mismatch", "Retained mask hash does not match.")
        _validate_png(package / mask_path, None, None)
        _validate_jpeg(package / overlay_path)
        referenced_files.update((mask_path, overlay_path))


def _validate_backend_model(evidence: dict[str, object], authority: dict[str, object]) -> None:
    backend = evidence.get("backend")
    approved_backend = authority["backend"]
    if not isinstance(backend, dict):
        raise EvidenceError("invalid_backend_evidence", "Observed backend metadata is missing.")
    if any(is_mock_marker(str(value)) for value in backend.values() if isinstance(value, str)):
        raise EvidenceError("mock_evidence_forbidden", "Mock backend markers are forbidden in real evidence.")
    for key in ("type", "implementation", "local"):
        if backend.get(key) != approved_backend.get(key):
            raise EvidenceError("backend_authority_mismatch", "Observed backend differs from approved authority.")
    if not _nonempty(backend.get("version")):
        raise EvidenceError("invalid_backend_evidence", "Observed backend version is required.")
    model = evidence.get("model")
    if not isinstance(model, dict):
        raise EvidenceError("invalid_model_evidence", "Observed model metadata is missing.")
    approved = next((item for item in authority["models"] if item.get("id") == model.get("id")), None)
    if approved is None:
        raise EvidenceError("model_authority_mismatch", "Observed model is not approved.")
    for key in ("sha256", "source", "license_id", "license_url"):
        if model.get(key) != approved.get(key):
            raise EvidenceError("model_authority_mismatch", "Observed model facts differ from approved authority.")


def _validate_host_environment(evidence: dict[str, object]) -> None:
    host = evidence.get("host")
    environment = evidence.get("environment")
    if not isinstance(host, dict) or not all(_nonempty(host.get(key)) for key in ("name", "version")):
        raise EvidenceError("invalid_host_evidence", "Observed host name and version are required.")
    if not isinstance(environment, dict) or not all(
        _nonempty(environment.get(key)) for key in ("os", "python", "gpu", "cuda")
    ):
        raise EvidenceError("invalid_environment_evidence", "Observed environment facts are required.")


def _validate_artifact(package: Path, value: object, expected_mime: str) -> str:
    if not isinstance(value, dict):
        raise EvidenceError("invalid_artifact_evidence", "Artifact metadata is missing.")
    relative = _relative_file(package, value.get("path"))
    path = package / relative
    if not path.is_file():
        raise EvidenceError("evidence_file_missing", f"Retained artifact is missing: {relative}")
    if not _valid_sha(value.get("sha256")) or sha256_file(path) != value.get("sha256"):
        raise EvidenceError("artifact_hash_mismatch", f"Retained artifact hash differs: {relative}")
    width = value.get("width")
    height = value.get("height")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise EvidenceError("invalid_artifact_evidence", "Artifact dimensions are invalid.")
    if value.get("mime_type") != expected_mime:
        raise EvidenceError("invalid_artifact_evidence", "Artifact MIME type is invalid.")
    if expected_mime == "image/png":
        _validate_png(path, width, height)
    else:
        _validate_jpeg(path)
    return relative


def _validate_png(path: Path, expected_width: int | None, expected_height: int | None) -> tuple[int, int]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise EvidenceError("invalid_png_evidence", f"Cannot read PNG: {path.name}") from error
    if (
        len(data) < 33
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or data[12:16] != b"IHDR"
        or data[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"
    ):
        raise EvidenceError("invalid_png_evidence", f"Invalid PNG structure: {path.name}")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0 or expected_width not in (None, width) or expected_height not in (None, height):
        raise EvidenceError("invalid_png_evidence", f"PNG dimensions differ: {path.name}")
    return width, height


def _validate_jpeg(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise EvidenceError("invalid_jpeg_evidence", f"Cannot read JPEG: {path.name}") from error
    if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        raise EvidenceError("invalid_jpeg_evidence", f"Invalid JPEG markers: {path.name}")


def _relative_file(package: Path, value: object) -> str:
    path = resolve_relative(package, value)
    if not path.is_file():
        raise EvidenceError("evidence_file_missing", f"Referenced artifact is missing: {value}")
    return path.relative_to(package.resolve()).as_posix()


def _has_preview_warning(manifest: dict[str, object], round_value: dict[str, object]) -> bool:
    warnings: list[object] = []
    for source in (manifest.get("warnings"), round_value.get("warnings")):
        if isinstance(source, list):
            warnings.extend(source)
    return any(isinstance(item, str) and item.startswith("preview_unavailable") for item in warnings)


def _load_briefs(path: Path) -> list[dict[str, object]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("invalid_acceptance_briefs", "Acceptance brief fixture cannot be read.") from error
    if not isinstance(value, list) or len(value) != 9 or not all(isinstance(item, dict) for item in value):
        raise EvidenceError("invalid_acceptance_briefs", "Acceptance fixture must contain exactly nine briefs.")
    ids = [item.get("id") for item in value]
    if not all(_nonempty(item) for item in ids) or len(set(ids)) != 9:
        raise EvidenceError("invalid_acceptance_briefs", "Acceptance brief IDs must be unique.")
    return value


def _load_object(path: Path, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(code, f"Cannot read JSON evidence: {path.name}") from error
    if not isinstance(value, dict):
        raise EvidenceError(code, f"JSON evidence must be an object: {path.name}")
    return value


def _package_ids(root: Path) -> set[str]:
    if not root.exists():
        return set()
    if not root.is_dir():
        raise EvidenceError("invalid_evidence_root", f"Evidence collection is not a directory: {root.name}")
    return {item.name for item in root.iterdir() if item.is_dir()}


def _reject_links(root: Path) -> None:
    if not root.exists():
        return
    candidates = [root]
    for current, directories, files in os.walk(root, followlinks=False):
        candidates.extend(Path(current) / name for name in directories + files)
    for path in candidates:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise EvidenceError("evidence_file_unreadable", f"Cannot inspect evidence path: {path.name}") from error
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise EvidenceError("evidence_symlink_forbidden", "Symlinks and reparse points are forbidden in evidence.")


def _require_timestamp(value: object, code: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError(code, "Timestamp must use RFC 3339 UTC form.")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise EvidenceError(code, "Timestamp must use RFC 3339 UTC form.") from error


def _is_absolute_path(value: str) -> bool:
    return (
        Path(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith(("\\\\", "//"))
    )


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "docs" / "evidence")
    parser.add_argument(
        "--briefs",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "acceptance" / "v1-briefs.json",
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = validate_evidence(args.root, args.briefs, args.strict)
    except EvidenceError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
