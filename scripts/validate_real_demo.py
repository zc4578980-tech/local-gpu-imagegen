#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from local_gpu_imagegen.visual_review import visual_checks_pass
from validate_client_sessions import validate_session


MODEL_ID = "local:1a4a27ae037d08ad44e98772"
MODEL_TOKEN = "model:1a4a27ae037d08ad44e987720d07df0910fff0e1d3210378e6a4886cfc4f97a5"
MODEL_SHA256 = "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"
WORKFLOW_SHA256 = "05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e"
BUNDLE_SHA256 = "ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62"
EXPECTED_SERVER_VERSION = "0.6.1"
EXPECTED_FILES = {
    "before.png",
    "after.png",
    "before-preview.jpg",
    "after-preview.jpg",
    "root-manifest.json",
    "revision-manifest.json",
    "transcript.md",
    "showcase.gif",
    "showcase-manifest.json",
    "README.md",
}
ARTIFACT_FILES = EXPECTED_FILES - {"showcase-manifest.json"}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "demo_kind",
    "model_output",
    "public_rights",
    "route",
    "root",
    "revision",
    "client_session",
    "artifacts",
    "known_limitations",
}
PUBLIC_RIGHTS_FIELDS = {
    "source",
    "license_id",
    "license_url",
    "output_redistribution_status",
}
ROUTE_FIELDS = {
    "authorization_scope",
    "backend",
    "model_id",
    "model_identity_token",
    "model_sha256",
    "workflow_template_id",
    "workflow_template_version",
    "workflow_sha256",
    "component_bundle_sha256",
    "prompt_compiler_id",
    "prompt_compiler_version",
    "width",
    "height",
    "steps",
    "guidance_scale",
    "sampler",
    "scheduler",
    "upscale_policy",
}
ROOT_FIELDS = {
    "run_id",
    "round_number",
    "image_sha256",
    "seed",
    "quality_status",
    "confirmation",
    "visual_checks",
}
REVISION_FIELDS = {
    "run_id",
    "parent",
    "edit_mode",
    "preserve",
    "change",
    "round_number",
    "image_sha256",
    "seed",
    "quality_status",
    "confirmation",
    "finalization_verified",
    "preservation_results",
    "visual_checks",
}
CLIENT_SESSION_FIELDS = {"path", "sha256", "client", "version"}
ARTIFACT_FIELDS = {"path", "sha256", "bytes", "mime_type"}
EXPECTED_ROUTE = {
    "authorization_scope": "public_evidence",
    "backend": "comfyui",
    "model_id": MODEL_ID,
    "model_identity_token": MODEL_TOKEN,
    "model_sha256": MODEL_SHA256,
    "workflow_template_id": "sdxl-txt2img",
    "workflow_template_version": 1,
    "workflow_sha256": WORKFLOW_SHA256,
    "component_bundle_sha256": BUNDLE_SHA256,
    "prompt_compiler_id": "natural-v1",
    "prompt_compiler_version": 1,
    "width": 1280,
    "height": 720,
    "steps": 30,
    "guidance_scale": 7.0,
    "sampler": "dpmpp_2m",
    "scheduler": "karras",
    "upscale_policy": "off",
}
EXPECTED_RIGHTS = {
    "source": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
    "license_id": "CreativeML Open RAIL++-M",
    "license_url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
    "output_redistribution_status": "approved",
}
EXPECTED_PRESERVE = [
    {"target": "composition", "strength": "hard"},
    {"target": "primary_motif", "strength": "hard"},
    {"target": "left_safe_area", "strength": "hard"},
]
MIME_TYPES = {
    "before.png": "image/png",
    "after.png": "image/png",
    "before-preview.jpg": "image/jpeg",
    "after-preview.jpg": "image/jpeg",
    "root-manifest.json": "application/json",
    "revision-manifest.json": "application/json",
    "transcript.md": "text/markdown",
    "showcase.gif": "image/gif",
    "README.md": "text/markdown",
}
PRIVATE_KEYS = {
    "account_id",
    "authorization",
    "backend_url",
    "credential",
    "cwd",
    "endpoint",
    "endpoint_identity",
    "idempotency_key",
    "intent",
    "model_path",
    "negative_prompt",
    "output_root",
    "password",
    "positive_prompt",
    "prompt",
    "raw_prompt",
    "route_token",
    "secret",
    "token",
    "workflow_job_id",
}
PRIVATE_MARKERS = (
    "127.0.0.1",
    "localhost",
    "/home/",
    "/users/",
    "bearer ",
    "github_pat_",
    "ghp_",
    "hf_",
    "sk-",
)
WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|[^a-z0-9])[a-z]:[\\/]")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _contains_private_value(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            not isinstance(key, str)
            or key.casefold() in PRIVATE_KEYS
            or _contains_private_value(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_private_value(item) for item in value)
    if not isinstance(value, str):
        return False
    lowered = value.casefold()
    return (
        bool(WINDOWS_PATH_RE.search(value))
        or value.startswith("\\\\")
        or any(marker in lowered for marker in PRIVATE_MARKERS)
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _confirmation(run: object) -> str | None:
    if not isinstance(run, dict):
        return None
    run_id = run.get("run_id")
    round_number = run.get("round_number")
    image_sha256 = run.get("image_sha256")
    if (
        not isinstance(run_id, str)
        or not isinstance(round_number, int)
        or isinstance(round_number, bool)
        or not isinstance(image_sha256, str)
    ):
        return None
    return f"finalize:{run_id}:{round_number}:{image_sha256}"


def _validate_sanitized_manifests(root: Path, manifest: dict[str, object], findings: set[str]) -> None:
    try:
        root_document = _read_json(root / "root-manifest.json")
        revision_document = _read_json(root / "revision-manifest.json")
    except (OSError, UnicodeError, json.JSONDecodeError):
        findings.add("invalid_sanitized_manifests")
        return
    if _contains_private_value(root_document) or _contains_private_value(revision_document):
        findings.add("private_value")
    root_summary = manifest.get("root")
    revision_summary = manifest.get("revision")
    if (
        not isinstance(root_document, dict)
        or root_document.get("role") != "root"
        or not isinstance(root_summary, dict)
        or root_document.get("run_id") != root_summary.get("run_id")
        or root_document.get("image_sha256") != root_summary.get("image_sha256")
    ):
        findings.add("root_manifest_mismatch")
    if (
        not isinstance(revision_document, dict)
        or revision_document.get("role") != "revision"
        or not isinstance(revision_summary, dict)
        or revision_document.get("run_id") != revision_summary.get("run_id")
        or revision_document.get("image_sha256") != revision_summary.get("image_sha256")
        or revision_document.get("parent") != revision_summary.get("parent")
    ):
        findings.add("revision_manifest_mismatch")


def _validate_client_session(root: Path, value: object, findings: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != CLIENT_SESSION_FIELDS:
        findings.add("invalid_client_session_binding")
        return
    relative = value.get("path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        findings.add("invalid_client_session_path")
        return
    expected_root = (root.parents[1] / "evidence" / "client-sessions").resolve()
    client_path = (root / relative).resolve()
    if client_path.parent != expected_root or client_path.suffix != ".json":
        findings.add("invalid_client_session_path")
        return
    try:
        actual_sha256 = sha256_file(client_path)
        document = _read_json(client_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        findings.add("invalid_client_session")
        return
    if value.get("sha256") != actual_sha256:
        findings.add("client_session_sha256_mismatch")
    session_findings = validate_session(
        document,
        expected_server_version=EXPECTED_SERVER_VERSION,
    )
    if session_findings:
        findings.add("invalid_client_session")
    if not isinstance(document, dict) or not isinstance(document.get("client"), dict):
        findings.add("invalid_client_session")
        return
    if (
        value.get("client") != document["client"].get("name")
        or value.get("version") != document["client"].get("version")
    ):
        findings.add("client_session_identity_mismatch")


def validate_real_demo(root: Path) -> list[str]:
    root = Path(root)
    findings: set[str] = set()
    if not root.is_dir():
        return ["demo_directory_missing"]
    observed_files = {path.name for path in root.iterdir() if path.is_file()}
    if observed_files != EXPECTED_FILES:
        findings.add("unexpected_demo_files")
    manifest_path = root / "showcase-manifest.json"
    try:
        document = _read_json(manifest_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return sorted(findings | {"invalid_showcase_manifest"})
    if not isinstance(document, dict):
        return sorted(findings | {"invalid_showcase_manifest"})
    if set(document) != TOP_LEVEL_FIELDS:
        findings.add("invalid_showcase_manifest")
    if document.get("schema_version") != "1.0":
        findings.add("invalid_showcase_manifest")
    if document.get("demo_kind") != "real_local_gpu_hot_revision":
        findings.add("invalid_demo_kind")
    if document.get("model_output") is not True:
        findings.add("not_real_model_output")
    if _contains_private_value(document):
        findings.add("private_value")

    rights = document.get("public_rights")
    if (
        not isinstance(rights, dict)
        or set(rights) != PUBLIC_RIGHTS_FIELDS
        or rights != EXPECTED_RIGHTS
    ):
        findings.add("invalid_public_rights")
    route = document.get("route")
    if (
        not isinstance(route, dict)
        or set(route) != ROUTE_FIELDS
        or route != EXPECTED_ROUTE
    ):
        findings.add("invalid_public_route")

    root_summary = document.get("root")
    if not isinstance(root_summary, dict) or set(root_summary) != ROOT_FIELDS:
        findings.add("invalid_root_summary")
    else:
        if root_summary.get("quality_status") != "candidate":
            findings.add("invalid_root_quality_status")
        if root_summary.get("confirmation") != _confirmation(root_summary):
            findings.add("invalid_root_confirmation")
        if not visual_checks_pass(root_summary.get("visual_checks")):
            findings.add("visual_checks_not_passed:root")

    revision = document.get("revision")
    if not isinstance(revision, dict) or set(revision) != REVISION_FIELDS:
        findings.add("invalid_revision_summary")
    else:
        parent = revision.get("parent")
        expected_parent = (
            {
                "run_id": root_summary.get("run_id"),
                "round": root_summary.get("round_number"),
                "image_sha256": root_summary.get("image_sha256"),
            }
            if isinstance(root_summary, dict)
            else None
        )
        if parent != expected_parent:
            findings.add("invalid_revision_lineage")
        if revision.get("edit_mode") != "prompt-refine":
            findings.add("invalid_revision_edit_mode")
        if revision.get("preserve") != EXPECTED_PRESERVE:
            findings.add("invalid_preserve_contract")
        if revision.get("change") != ["palette_and_lighting"]:
            findings.add("invalid_change_contract")
        if revision.get("quality_status") != "accepted" or revision.get("finalization_verified") is not True:
            findings.add("invalid_revision_finalization")
        if revision.get("confirmation") != _confirmation(revision):
            findings.add("invalid_revision_confirmation")
        if not visual_checks_pass(revision.get("visual_checks")):
            findings.add("visual_checks_not_passed:revision")
        preservation = revision.get("preservation_results")
        if (
            not isinstance(preservation, list)
            or [item.get("target") for item in preservation if isinstance(item, dict)]
            != [item["target"] for item in EXPECTED_PRESERVE]
            or any(
                not isinstance(item, dict) or item.get("status") != "preserved"
                for item in preservation
            )
        ):
            findings.add("preservation_not_passed")
        if isinstance(root_summary, dict) and revision.get("seed") != root_summary.get("seed"):
            findings.add("seed_not_preserved")

    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != ARTIFACT_FILES:
        findings.add("invalid_artifact_manifest")
    else:
        for name in sorted(ARTIFACT_FILES):
            metadata = artifacts.get(name)
            if (
                not isinstance(metadata, dict)
                or set(metadata) != ARTIFACT_FIELDS
                or metadata.get("path") != name
                or metadata.get("mime_type") != MIME_TYPES[name]
                or not isinstance(metadata.get("bytes"), int)
                or isinstance(metadata.get("bytes"), bool)
                or metadata.get("bytes", 0) <= 0
                or not isinstance(metadata.get("sha256"), str)
                or not SHA256_RE.fullmatch(metadata["sha256"])
            ):
                findings.add(f"invalid_artifact_metadata:{name}")
                continue
            path = root / name
            try:
                actual_size = path.stat().st_size
                actual_sha256 = sha256_file(path)
            except OSError:
                findings.add(f"artifact_missing:{name}")
                continue
            if actual_size != metadata["bytes"]:
                findings.add(f"artifact_size_mismatch:{name}")
            if actual_sha256 != metadata["sha256"]:
                findings.add(f"artifact_sha256_mismatch:{name}")

    limitations = document.get("known_limitations")
    if (
        not isinstance(limitations, list)
        or len(limitations) < 3
        or not all(isinstance(item, str) and item.strip() for item in limitations)
    ):
        findings.add("missing_known_limitations")

    _validate_client_session(root, document.get("client_session"), findings)
    _validate_sanitized_manifests(root, document, findings)
    for name in ("transcript.md", "README.md"):
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.add(f"artifact_missing:{name}")
            continue
        if _contains_private_value(text):
            findings.add("private_value")
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the genuine public hot-revision demo.")
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    findings = validate_real_demo(args.root)
    report = {"ok": not findings, "findings": findings}
    print(json.dumps(report, indent=2, sort_keys=True), file=None if not findings else sys.stderr)
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
