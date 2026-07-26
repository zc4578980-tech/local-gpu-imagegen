#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import stat
import sys
from pathlib import Path

from local_gpu_imagegen import __version__
from local_gpu_imagegen.artifacts import validate_png
from local_gpu_imagegen.errors import ArtifactError
from local_gpu_imagegen.visual_review import visual_checks_pass
from validate_client_sessions import validate_session


MODEL_ID = "local:1a4a27ae037d08ad44e98772"
MODEL_TOKEN = "model:89bf0283e0c284f8f84f8849035374bbdb60491e5a5665f801b3ec10b92d8b23"
MODEL_SHA256 = "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"
WORKFLOW_SHA256 = "05f942291676182d08446b8855d6353a96e10fa3b059703a9f6d41e16d36000e"
BUNDLE_SHA256 = "ec5ea6fdae221003e32e7e6cac42609a0b62af24f2996a7d46826b153f360f62"
EXPECTED_SERVER_VERSION = __version__
EXPECTED_FILES = {
    "final.png",
    "preview.jpg",
    "run-manifest.json",
    "mcp-result.json",
    "transcript.md",
    "showcase-manifest.json",
    "README.md",
}
ARTIFACT_FILES = EXPECTED_FILES - {"showcase-manifest.json"}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "demo_kind",
    "model_output",
    "installed_package",
    "public_rights",
    "route",
    "generation",
    "final",
    "client_session",
    "mcp_result",
    "artifacts",
    "known_limitations",
}
INSTALLED_PACKAGE_FIELDS = {"version", "wheel_sha256"}
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
}
GENERATION_FIELDS = {
    "positive_prompt",
    "negative_prompt",
    "seed",
    "width",
    "height",
    "steps",
    "guidance_scale",
    "sampler",
    "scheduler",
}
FINAL_FIELDS = {
    "run_id",
    "round_number",
    "image_sha256",
    "bytes",
    "width",
    "height",
    "mime_type",
    "quality_status",
    "confirmation",
    "finalization_verified",
    "visual_checks",
}
CLIENT_SESSION_FIELDS = {"path", "sha256", "client", "version", "session_purpose"}
MCP_RESULT_FIELDS = {"path", "sha256", "source_sha256", "tool"}
PUBLIC_MCP_FIELDS = {
    "schema_version",
    "tool",
    "source_sha256",
    "ok",
    "run_id",
    "state",
    "final",
}
PUBLIC_MCP_FINAL_FIELDS = {"round_number", "quality_status", "image_sha256"}
ARTIFACT_FIELDS = {"path", "sha256", "bytes", "mime_type"}
RUN_MANIFEST_FIELDS = {
    "schema_version",
    "role",
    "run_id",
    "state",
    "parent",
    "round_number",
    "image_sha256",
    "route",
    "generation",
    "review",
    "final",
}
REVIEW_FIELDS = {
    "round_number",
    "reviewed_at",
    "scores",
    "rubric",
    "applicable_constraints",
    "constraint_results",
    "critique",
    "hard_failures",
    "next_action",
    "visual_checks",
}
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
}
EXPECTED_RIGHTS = {
    "source": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
    "license_id": "CreativeML Open RAIL++-M",
    "license_url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
    "output_redistribution_status": "approved",
}
MIME_TYPES = {
    "final.png": "image/png",
    "preview.jpg": "image/jpeg",
    "run-manifest.json": "application/json",
    "mcp-result.json": "application/json",
    "transcript.md": "text/markdown",
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
    "output_root",
    "password",
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
    "endpoint:",
)
WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|[^a-z0-9])[a-z]:[\\/]")
EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
URL_RE = re.compile(r"(?i)\bhttps?://[^\s]+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PUBLIC_URLS = {EXPECTED_RIGHTS["source"], EXPECTED_RIGHTS["license_url"]}


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
    if value in PUBLIC_URLS:
        return False
    lowered = value.casefold()
    return (
        bool(WINDOWS_PATH_RE.search(value))
        or value.startswith("\\\\")
        or any(marker in lowered for marker in PRIVATE_MARKERS)
        or bool(EMAIL_RE.search(value))
        or bool(URL_RE.search(value))
    )


def _read_json(path: Path) -> object:
    if not _is_safe_regular_file(path):
        raise OSError("unsafe JSON file")
    return json.loads(path.read_text(encoding="utf-8"))


def _confirmation(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    run_id = value.get("run_id")
    round_number = value.get("round_number")
    image_sha256 = value.get("image_sha256")
    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(round_number, int)
        or isinstance(round_number, bool)
        or not isinstance(image_sha256, str)
    ):
        return None
    return f"finalize:{run_id}:{round_number}:{image_sha256}"


def _is_safe_regular_file(path: Path) -> bool:
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


def _is_safe_directory(path: Path) -> bool:
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


def _valid_dimension(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 256 <= value <= 1536
        and value % 8 == 0
    )


def _valid_generation(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != GENERATION_FIELDS:
        return False
    seed = value.get("seed")
    steps = value.get("steps")
    guidance = value.get("guidance_scale")
    return (
        isinstance(value.get("positive_prompt"), str)
        and bool(value["positive_prompt"].strip())
        and isinstance(value.get("negative_prompt"), str)
        and bool(value["negative_prompt"].strip())
        and isinstance(seed, int)
        and not isinstance(seed, bool)
        and seed >= 0
        and _valid_dimension(value.get("width"))
        and _valid_dimension(value.get("height"))
        and isinstance(steps, int)
        and not isinstance(steps, bool)
        and steps > 0
        and isinstance(guidance, (int, float))
        and not isinstance(guidance, bool)
        and guidance > 0
        and isinstance(value.get("sampler"), str)
        and bool(value["sampler"].strip())
        and isinstance(value.get("scheduler"), str)
        and bool(value["scheduler"].strip())
    )


def _valid_review(value: object, final: object) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != REVIEW_FIELDS
        or not isinstance(final, dict)
        or value.get("round_number") != final.get("round_number")
        or not isinstance(value.get("reviewed_at"), str)
        or not value["reviewed_at"].strip()
        or not isinstance(value.get("critique"), str)
        or not value["critique"].strip()
        or len(value["critique"].strip()) > 2000
        or value.get("hard_failures") != []
        or value.get("next_action") != "finalize"
        or value.get("visual_checks") != final.get("visual_checks")
        or not visual_checks_pass(value.get("visual_checks"))
    ):
        return False
    scores = value.get("scores")
    rubric = value.get("rubric")
    if (
        not isinstance(scores, dict)
        or not isinstance(rubric, dict)
        or not rubric
        or set(scores) != set(rubric)
        or any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(score, int)
            or isinstance(score, bool)
            or not 1 <= score <= 5
            for name, score in scores.items()
        )
        or any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(specification, dict)
            or set(specification) != {"critical", "weight"}
            or not isinstance(specification.get("critical"), bool)
            or not isinstance(specification.get("weight"), (int, float))
            or isinstance(specification.get("weight"), bool)
            or not math.isfinite(specification["weight"])
            or specification["weight"] <= 0
            or specification["critical"] is True
            and scores.get(name, 0) < 3
            for name, specification in rubric.items()
        )
    ):
        return False
    applicable = value.get("applicable_constraints")
    constraints = value.get("constraint_results")
    return (
        isinstance(applicable, list)
        and bool(applicable)
        and all(isinstance(name, str) and name.strip() for name in applicable)
        and applicable == sorted(set(applicable))
        and isinstance(constraints, dict)
        and set(constraints) == set(applicable)
        and all(
            isinstance(name, str)
            and bool(name.strip())
            and isinstance(result, dict)
            and set(result) == {"status", "observation"}
            and result.get("status") == "pass"
            and isinstance(result.get("observation"), str)
            and bool(result["observation"].strip())
            for name, result in constraints.items()
        )
    )


def _validate_artifacts(
    root: Path,
    value: object,
    final: object,
    findings: set[str],
) -> None:
    if not isinstance(value, dict) or set(value) != ARTIFACT_FILES:
        findings.add("invalid_artifact_manifest")
        return
    for name in sorted(ARTIFACT_FILES):
        metadata = value.get(name)
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
        if not _is_safe_regular_file(path):
            findings.add(f"artifact_missing:{name}")
            continue
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
        if name == "final.png":
            if (
                not isinstance(final, dict)
                or not _valid_dimension(final.get("width"))
                or not _valid_dimension(final.get("height"))
            ):
                findings.add("invalid_final_png")
            else:
                try:
                    validated = validate_png(
                        path,
                        final["width"],
                        final["height"],
                    )
                except (ArtifactError, OSError, ValueError):
                    findings.add("invalid_final_png")
                else:
                    if validated.get("sha256") != metadata["sha256"]:
                        findings.add("artifact_sha256_mismatch:final.png")
        elif name == "preview.jpg":
            try:
                encoded = path.read_bytes()
            except OSError:
                findings.add("artifact_missing:preview.jpg")
            else:
                if (
                    len(encoded) > 1024 * 1024
                    or not encoded.startswith(b"\xff\xd8")
                    or not encoded.endswith(b"\xff\xd9")
                ):
                    findings.add("invalid_preview_jpeg")


def _validate_client_session(
    root: Path,
    binding: object,
    installed_package: object,
    final: object,
    findings: set[str],
    *,
    expected_server_version: str,
) -> None:
    if not isinstance(binding, dict) or set(binding) != CLIENT_SESSION_FIELDS:
        findings.add("invalid_client_session_binding")
        return
    relative = binding.get("path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        findings.add("invalid_client_session_path")
        return
    expected_root = (root.parents[1] / "evidence" / "client-sessions").resolve()
    client_path = (root / relative).resolve()
    if (
        client_path.parent != expected_root
        or client_path.suffix != ".json"
        or not _is_safe_regular_file(client_path)
    ):
        findings.add("invalid_client_session_path")
        return
    try:
        actual_sha256 = sha256_file(client_path)
        document = _read_json(client_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        findings.add("invalid_client_session")
        return
    if binding.get("sha256") != actual_sha256:
        findings.add("client_session_sha256_mismatch")
    if validate_session(document, expected_server_version=expected_server_version):
        findings.add("invalid_client_session")
    if not isinstance(document, dict) or not isinstance(document.get("client"), dict):
        findings.add("invalid_client_session")
        return
    client = document["client"]
    if (
        binding.get("client") != client.get("name")
        or binding.get("version") != client.get("version")
        or binding.get("session_purpose") != "golden_generation"
        or document.get("session_purpose") != "golden_generation"
    ):
        findings.add("client_session_identity_mismatch")
    server = document.get("server")
    if (
        not isinstance(installed_package, dict)
        or not isinstance(server, dict)
        or installed_package.get("version") != server.get("version")
        or installed_package.get("wheel_sha256") != server.get("wheel_sha256")
    ):
        findings.add("installed_package_client_mismatch")
    if isinstance(final, dict):
        matching_generation = any(
            isinstance(call, dict)
            and call.get("name") == "local_gpu_generate_round"
            and isinstance(call.get("result"), dict)
            and call["result"].get("run_id") == final.get("run_id")
            and call["result"].get("round_number") == final.get("round_number")
            and call["result"].get("image_sha256") == final.get("image_sha256")
            for call in document.get("tool_calls", [])
        )
        if not matching_generation:
            findings.add("client_generation_binding_mismatch")


def _validate_public_mcp_result(
    root: Path,
    binding: object,
    final: object,
    findings: set[str],
) -> None:
    if not isinstance(binding, dict) or set(binding) != MCP_RESULT_FIELDS:
        findings.add("invalid_mcp_result_binding")
        return
    path = root / "mcp-result.json"
    try:
        document = _read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        findings.add("invalid_public_mcp_result")
        return
    source_sha256 = binding.get("source_sha256")
    if (
        not isinstance(source_sha256, str)
        or not SHA256_RE.fullmatch(source_sha256)
        or source_sha256 == "0" * 64
        or not isinstance(document, dict)
        or document.get("source_sha256") != source_sha256
    ):
        findings.add("mcp_source_sha256_invalid")
    if (
        binding.get("path") != "mcp-result.json"
        or binding.get("tool") != "local_gpu_finalize_run"
        or binding.get("sha256") != sha256_file(path)
    ):
        findings.add("mcp_result_sha256_mismatch")
    if not isinstance(document, dict) or set(document) != PUBLIC_MCP_FIELDS:
        findings.add("invalid_public_mcp_result")
        return
    public_final = document.get("final")
    if (
        document.get("schema_version") != "1.0"
        or document.get("tool") != "local_gpu_finalize_run"
        or document.get("ok") is not True
        or document.get("state") != "finalized"
        or not isinstance(public_final, dict)
        or set(public_final) != PUBLIC_MCP_FINAL_FIELDS
        or not isinstance(final, dict)
        or document.get("run_id") != final.get("run_id")
        or public_final.get("round_number") != final.get("round_number")
        or public_final.get("quality_status") != "accepted"
        or public_final.get("image_sha256") != final.get("image_sha256")
        or _contains_private_value(document)
    ):
        findings.add("invalid_public_mcp_result")


def _validate_run_manifest(
    root: Path,
    route: object,
    generation: object,
    final: object,
    findings: set[str],
) -> None:
    try:
        document = _read_json(root / "run-manifest.json")
    except (OSError, UnicodeError, json.JSONDecodeError):
        findings.add("run_manifest_mismatch")
        return
    contains_private = isinstance(document, dict) and _contains_private_value(document)
    invalid_shape = (
        not isinstance(document, dict)
        or set(document) != RUN_MANIFEST_FIELDS
        or document.get("schema_version") != "2.0"
        or document.get("role") != "finalized_root"
        or document.get("state") != "finalized"
        or document.get("parent") is not None
        or not isinstance(final, dict)
        or document.get("run_id") != final.get("run_id")
        or document.get("round_number") != final.get("round_number")
        or document.get("image_sha256") != final.get("image_sha256")
        or document.get("route") != route
        or document.get("generation") != generation
        or document.get("final") != final
    )
    if contains_private:
        findings.add("private_value")
    if invalid_shape:
        findings.add("run_manifest_mismatch")
        return
    if not _valid_review(document.get("review"), final):
        findings.add("invalid_review_evidence")


def validate_real_demo(
    root: Path,
    *,
    expected_server_version: str = EXPECTED_SERVER_VERSION,
) -> list[str]:
    root = Path(root)
    findings: set[str] = set()
    if not _is_safe_directory(root):
        return ["demo_directory_missing"]
    try:
        observed_entries = {path.name for path in root.iterdir()}
    except OSError:
        return ["demo_directory_missing"]
    if observed_entries != EXPECTED_FILES:
        findings.add("unexpected_demo_files")
    try:
        document = _read_json(root / "showcase-manifest.json")
    except (OSError, UnicodeError, json.JSONDecodeError):
        return sorted(findings | {"invalid_showcase_manifest"})
    if not isinstance(document, dict):
        return sorted(findings | {"invalid_showcase_manifest"})
    if set(document) != TOP_LEVEL_FIELDS or document.get("schema_version") != "2.0":
        findings.add("invalid_showcase_manifest")
    if document.get("demo_kind") != "real_local_gpu_generation":
        findings.add("invalid_demo_kind")
    if document.get("model_output") is not True:
        findings.add("not_real_model_output")
    if _contains_private_value(document):
        findings.add("private_value")

    installed = document.get("installed_package")
    if not isinstance(installed, dict) or set(installed) != INSTALLED_PACKAGE_FIELDS:
        findings.add("invalid_installed_package")
    else:
        wheel_sha256 = installed.get("wheel_sha256")
        if installed.get("version") != expected_server_version:
            findings.add("server_version_mismatch")
        if (
            not isinstance(wheel_sha256, str)
            or not SHA256_RE.fullmatch(wheel_sha256)
            or wheel_sha256 == "0" * 64
        ):
            findings.add("invalid_wheel_sha256")

    rights = document.get("public_rights")
    if (
        not isinstance(rights, dict)
        or set(rights) != PUBLIC_RIGHTS_FIELDS
        or rights != EXPECTED_RIGHTS
    ):
        findings.add("invalid_public_rights")
    route = document.get("route")
    if not isinstance(route, dict) or set(route) != ROUTE_FIELDS or route != EXPECTED_ROUTE:
        findings.add("invalid_public_route")
    generation = document.get("generation")
    if not _valid_generation(generation):
        findings.add("invalid_generation_provenance")

    final = document.get("final")
    if not isinstance(final, dict) or set(final) != FINAL_FIELDS:
        findings.add("invalid_finalization")
    else:
        if (
            final.get("quality_status") != "accepted"
            or final.get("finalization_verified") is not True
            or final.get("confirmation") != _confirmation(final)
            or final.get("mime_type") != "image/png"
            or not _valid_dimension(final.get("width"))
            or not _valid_dimension(final.get("height"))
            or not isinstance(final.get("bytes"), int)
            or isinstance(final.get("bytes"), bool)
            or final.get("bytes", 0) <= 0
            or not isinstance(final.get("image_sha256"), str)
            or not SHA256_RE.fullmatch(final["image_sha256"])
        ):
            findings.add("invalid_finalization")
        if not visual_checks_pass(final.get("visual_checks")):
            findings.add("visual_checks_not_passed")
        if isinstance(generation, dict) and (
            final.get("width") != generation.get("width")
            or final.get("height") != generation.get("height")
        ):
            findings.add("invalid_generation_provenance")

    artifacts = document.get("artifacts")
    _validate_artifacts(root, artifacts, final, findings)
    if isinstance(artifacts, dict) and isinstance(final, dict):
        image_artifact = artifacts.get("final.png")
        if (
            not isinstance(image_artifact, dict)
            or image_artifact.get("sha256") != final.get("image_sha256")
            or image_artifact.get("bytes") != final.get("bytes")
        ):
            findings.add("final_artifact_mismatch")

    limitations = document.get("known_limitations")
    if (
        not isinstance(limitations, list)
        or len(limitations) < 3
        or not all(isinstance(item, str) and item.strip() for item in limitations)
    ):
        findings.add("missing_known_limitations")

    _validate_client_session(
        root,
        document.get("client_session"),
        installed,
        final,
        findings,
        expected_server_version=expected_server_version,
    )
    _validate_public_mcp_result(root, document.get("mcp_result"), final, findings)
    _validate_run_manifest(root, route, generation, final, findings)
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
    parser = argparse.ArgumentParser(description="Validate a genuine ordinary-route demo.")
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--expected-server-version",
        default=EXPECTED_SERVER_VERSION,
        help="Exact server version retained by this demo.",
    )
    args = parser.parse_args()
    findings = validate_real_demo(
        args.root,
        expected_server_version=args.expected_server_version,
    )
    report = {"ok": not findings, "findings": findings}
    print(json.dumps(report, indent=2, sort_keys=True), file=None if not findings else sys.stderr)
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
