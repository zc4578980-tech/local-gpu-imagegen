#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from local_gpu_imagegen import __version__
from verify_mcp import DEFAULT_EXPECTED_TOOLS


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|[^a-z0-9])[a-z]:[\\/]")
EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "evidence_class",
    "session_purpose",
    "client",
    "installed_wheel",
    "hosted_client_session",
    "server",
    "started_at",
    "completed_at",
    "tool_calls",
    "sanitization",
}
CLIENT_FIELDS = {"name", "version", "session_mode"}
SERVER_FIELDS = {"name", "version", "protocol_version", "wheel_sha256"}
TOOL_CALL_FIELDS = {"sequence", "name", "result", "result_sha256"}
SANITIZATION_FIELDS = {
    "prompts_omitted",
    "account_identifiers_omitted",
    "credentials_omitted",
    "machine_paths_omitted",
    "raw_transcript_retained",
}
SESSION_MODES = {
    "codex": "ephemeral",
    "claude-code": "no_session_persistence",
}
SESSION_PURPOSES = {"compatibility", "golden_generation"}
GOLDEN_GENERATION_TOOLS = {
    "local_gpu_start_run",
    "local_gpu_generate_round",
}
RUN_LIFECYCLE_TOOLS = {
    "local_gpu_start_run",
    "local_gpu_get_run",
    "local_gpu_branch_run",
    "local_gpu_prepare_mask",
    "local_gpu_confirm_mask",
    "local_gpu_generate_round",
    "local_gpu_record_review",
    "local_gpu_finalize_run",
    "local_gpu_cleanup_run",
}
PRIVATE_RESULT_KEYS = {
    "account",
    "account_id",
    "authorization",
    "backend_url",
    "credential",
    "cwd",
    "email",
    "endpoint",
    "home",
    "idempotency_key",
    "output_root",
    "password",
    "path",
    "prompt",
    "raw_prompt",
    "secret",
    "token",
    "url",
}
PRIVATE_VALUE_MARKERS = (
    "127.0.0.1",
    "localhost",
    "http://[::1]",
    "https://[::1]",
    "/home/",
    "/users/",
    "bearer ",
    "github_pat_",
    "ghp_",
    "hf_",
    "sk-",
)
MAX_SESSION_DURATION = timedelta(hours=1)


def _canonical_result(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo != timezone.utc:
        return None
    return parsed


def _private_key(key: object) -> bool:
    if not isinstance(key, str):
        return True
    normalized = key.casefold()
    return (
        normalized in PRIVATE_RESULT_KEYS
        or normalized.endswith("_path")
        or normalized.endswith("_url")
        or normalized.endswith("_endpoint")
        or normalized.endswith("_prompt")
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
    )


def _contains_private_value(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _private_key(key) or _contains_private_value(item)
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
        or any(marker in lowered for marker in PRIVATE_VALUE_MARKERS)
        or bool(EMAIL_RE.search(value))
    )


def validate_session(
    document: object,
    *,
    expected_server_version: str,
) -> list[str]:
    findings: set[str] = set()
    if not isinstance(document, dict):
        return ["invalid_document"]
    if set(document) != TOP_LEVEL_FIELDS:
        findings.add("invalid_top_level_fields")
    if document.get("schema_version") != "1.0":
        findings.add("invalid_schema_version")
    if document.get("evidence_class") != "named_client_session":
        findings.add("invalid_evidence_class")
    purpose = document.get("session_purpose")
    if purpose not in SESSION_PURPOSES:
        findings.add("invalid_session_purpose")
    if document.get("installed_wheel") is not True:
        findings.add("installed_wheel_required")
    if document.get("hosted_client_session") is not True:
        findings.add("hosted_client_session_required")

    client = document.get("client")
    client_name: str | None = None
    if not isinstance(client, dict) or set(client) != CLIENT_FIELDS:
        findings.add("invalid_client")
    else:
        name = client.get("name")
        if name not in SESSION_MODES:
            findings.add("invalid_client")
        else:
            client_name = name
            if client.get("session_mode") != SESSION_MODES[name]:
                findings.add("invalid_session_mode")
        version = client.get("version")
        if (
            not isinstance(version, str)
            or not version.strip()
            or len(version) > 200
            or "\n" in version
            or "\r" in version
        ):
            findings.add("invalid_client_version")

    server = document.get("server")
    if not isinstance(server, dict) or set(server) != SERVER_FIELDS:
        findings.add("invalid_server")
    else:
        if (
            server.get("name") != "local-gpu-imagegen"
            or server.get("protocol_version") != "2024-11-05"
        ):
            findings.add("invalid_server")
        if server.get("version") != expected_server_version:
            findings.add("server_version_mismatch")
        wheel_sha256 = server.get("wheel_sha256")
        if not isinstance(wheel_sha256, str) or not SHA256_RE.fullmatch(wheel_sha256):
            findings.add("invalid_wheel_sha256")

    started_at = _parse_utc_timestamp(document.get("started_at"))
    completed_at = _parse_utc_timestamp(document.get("completed_at"))
    if started_at is None or completed_at is None:
        findings.add("invalid_timestamp")
    elif completed_at < started_at:
        findings.add("invalid_time_order")
    elif completed_at - started_at > MAX_SESSION_DURATION:
        findings.add("session_duration_exceeded")

    calls = document.get("tool_calls")
    observed_tools: set[str] = set()
    if not isinstance(calls, list) or not calls:
        findings.add("invalid_tool_calls")
    else:
        for expected_sequence, call in enumerate(calls, start=1):
            if not isinstance(call, dict) or set(call) != TOOL_CALL_FIELDS:
                findings.add("invalid_tool_calls")
                continue
            sequence = call.get("sequence")
            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence != expected_sequence
            ):
                findings.add("invalid_tool_sequence")
            name = call.get("name")
            if not isinstance(name, str) or name not in DEFAULT_EXPECTED_TOOLS:
                findings.add("unknown_tool")
            else:
                observed_tools.add(name)
            result = call.get("result")
            if not isinstance(result, dict):
                findings.add("invalid_tool_result")
                continue
            if purpose == "golden_generation" and name == "local_gpu_generate_round":
                run_id = result.get("run_id")
                round_number = result.get("round_number")
                image_sha256 = result.get("image_sha256")
                if (
                    not isinstance(run_id, str)
                    or not run_id.strip()
                    or not isinstance(round_number, int)
                    or isinstance(round_number, bool)
                    or round_number <= 0
                    or not isinstance(image_sha256, str)
                    or not SHA256_RE.fullmatch(image_sha256)
                ):
                    findings.add("invalid_golden_generation_result")
            if _contains_private_value(result):
                findings.add("private_value")
            try:
                actual_sha256 = hashlib.sha256(_canonical_result(result)).hexdigest()
            except (TypeError, ValueError, RecursionError):
                findings.add("invalid_tool_result")
                continue
            declared_sha256 = call.get("result_sha256")
            if (
                not isinstance(declared_sha256, str)
                or not SHA256_RE.fullmatch(declared_sha256)
                or declared_sha256 != actual_sha256
            ):
                findings.add("result_sha256_mismatch")
        if (
            "local_gpu_imagegen_check" not in observed_tools
            or not observed_tools.intersection(RUN_LIFECYCLE_TOOLS)
        ):
            findings.add("missing_required_tool_calls")
        if purpose == "golden_generation" and not GOLDEN_GENERATION_TOOLS <= observed_tools:
            findings.add("missing_golden_generation_calls")

    sanitization = document.get("sanitization")
    if (
        not isinstance(sanitization, dict)
        or set(sanitization) != SANITIZATION_FIELDS
        or any(
            sanitization.get(name) is not True
            for name in SANITIZATION_FIELDS - {"raw_transcript_retained"}
        )
        or sanitization.get("raw_transcript_retained") is not False
    ):
        findings.add("invalid_sanitization")

    if client_name is None:
        findings.add("invalid_client")
    return sorted(findings)


def validate_release_set(
    documents: list[object],
    *,
    expected_server_version: str,
) -> list[str]:
    findings: set[str] = set()
    valid_documents: list[dict[str, object]] = []
    for document in documents:
        findings.update(
            validate_session(
                document,
                expected_server_version=expected_server_version,
            )
        )
        if isinstance(document, dict):
            valid_documents.append(document)

    names = [
        client.get("name")
        for document in valid_documents
        if isinstance((client := document.get("client")), dict)
    ]
    if len(names) != 2 or sorted(name for name in names if isinstance(name, str)) != [
        "claude-code",
        "codex",
    ]:
        findings.add("named_client_release_set_required")
    if not any(
        document.get("session_purpose") == "golden_generation"
        for document in valid_documents
    ):
        findings.add("golden_generation_session_required")
    versions = {
        server.get("version")
        for document in valid_documents
        if isinstance((server := document.get("server")), dict)
    }
    if versions != {expected_server_version}:
        findings.add("release_set_server_version_mismatch")
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate sanitized real named-client MCP session evidence."
    )
    parser.add_argument(
        "--expected-server-version",
        default=__version__,
        help="Exact installed MCP server version required in every record.",
    )
    parser.add_argument(
        "--require-release-set",
        action="store_true",
        help="Require one Codex record, one Claude Code record, and a golden generation session.",
    )
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    input_documents: list[object] = []
    document_reports: list[dict[str, object]] = []
    ok = True
    for path in args.files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            input_documents.append(document)
            findings = validate_session(
                document,
                expected_server_version=args.expected_server_version,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings = [f"invalid_json:{type(exc).__name__}"]
        if findings:
            ok = False
        document_reports.append({"file": path.name, "findings": findings})

    release_set_findings: list[str] | None = None
    if args.require_release_set:
        release_set_findings = validate_release_set(
            input_documents,
            expected_server_version=args.expected_server_version,
        )
        if release_set_findings:
            ok = False

    report = {
        "ok": ok,
        "expected_server_version": args.expected_server_version,
        "validated_files": len(args.files),
        "documents": document_reports,
    }
    if release_set_findings is not None:
        report["release_set_findings"] = release_set_findings
    stream = None if ok else sys.stderr
    print(json.dumps(report, indent=2, sort_keys=True), file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
