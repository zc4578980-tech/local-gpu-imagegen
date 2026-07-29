"""Offline static checks for one Local GPU Imagegen release candidate wheel."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tomllib
import zipfile
from collections import Counter
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath
from typing import Callable


SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_WHEEL = "local_gpu_imagegen-0.8.0-py3-none-any.whl"
EXPECTED_VERSION = "0.8.0"
EXPECTED_REQUIRES_PYTHON = ">=3.11"
EXPECTED_DIST_INFO = "local_gpu_imagegen-0.8.0.dist-info"
MAX_ENTRIES = 256
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
# Allows ZIP overhead above the 16 MiB content limit while bounding file I/O.
MAX_WHEEL_BYTES = 32 * 1024 * 1024
PRIVATE_PATH_RE = re.compile(rb"(?i)(?:[a-z]:[\\/]+users[\\/]|/(?:home|users)/)")
CREDENTIAL_RE = re.compile(
    rb"(?i)(?:"
    rb"\b(?:authorization|proxy-authorization|x-api-key|api-key)\s*:|"
    rb"\b(?:api[_-]?key|client[_-]?secret|secret[_-]?key|access[_-]?token|"
    rb"refresh[_-]?token|auth[_-]?token|password|passwd|token)\s*[:=]|"
    rb"\bbearer\s+[a-z0-9._~+/=-]+"
    rb")"
)

GitRunner = Callable[..., subprocess.CompletedProcess[str]]


def passed_check(check_id: str, **observation: object) -> dict[str, object]:
    return {"id": check_id, "status": "passed", "observation": observation}


def blocked_check(check_id: str, code: str) -> dict[str, object]:
    return {"id": check_id, "status": "blocked", "code": code}


def _finalize_checks(results: list[dict[str, object]]) -> list[dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for result in results:
        check_id = str(result["id"])
        current = by_id.get(check_id)
        if current is None or (
            current["status"] == "passed" and result["status"] == "blocked"
        ):
            by_id[check_id] = result
    return [by_id[check_id] for check_id in sorted(by_id)]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        timeout=30, check=False,
    )


def _git_failed(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode != 0 and result.returncode != 1 or bool(result.stderr.strip())


def _run_git(
    runner: GitRunner,
    root: Path,
    *args: str,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return runner(root, *args)
    except (OSError, subprocess.SubprocessError):
        return None


def inspect_checkout(
    root: Path,
    expected_commit: str,
    *,
    runner: GitRunner = _git,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Inspect one checkout without changing it or accessing the network."""
    if not SHA1_RE.fullmatch(expected_commit):
        return [blocked_check("candidate_commit", "candidate_commit_invalid")], {}

    head = _run_git(runner, root, "rev-parse", "HEAD")
    if head is None or head.returncode != 0 or head.stderr.strip():
        return [blocked_check("git_checkout", "git_checkout_unavailable")], {}
    commit = head.stdout.strip()
    if not SHA1_RE.fullmatch(commit):
        return [blocked_check("git_checkout", "git_checkout_unavailable")], {}

    results: list[dict[str, object]] = []
    facts: dict[str, object] = {"commit": commit}
    if commit != expected_commit:
        results.append(blocked_check("candidate_commit", "candidate_commit_mismatch"))
    else:
        results.append(passed_check("candidate_commit", commit=commit))

    worktree = _run_git(runner, root, "diff", "--quiet")
    if worktree is None or _git_failed(worktree):
        results.append(blocked_check("git_checkout", "git_checkout_unavailable"))
    elif worktree.returncode == 1:
        results.append(blocked_check("tracked_worktree", "tracked_worktree_dirty"))
    else:
        results.append(passed_check("tracked_worktree"))

    index = _run_git(runner, root, "diff", "--cached", "--quiet")
    if index is None or _git_failed(index):
        results.append(blocked_check("git_checkout", "git_checkout_unavailable"))
    elif index.returncode == 1:
        results.append(blocked_check("index", "index_dirty"))
    else:
        results.append(passed_check("index"))

    status = _run_git(runner, root, "status", "--porcelain=v1")
    if status is None or status.returncode != 0 or status.stderr.strip():
        results.append(blocked_check("git_checkout", "git_checkout_unavailable"))
        return _finalize_checks(results), facts

    untracked_count = 0
    for line in status.stdout.splitlines():
        if line.startswith("?? "):
            untracked_count += 1
        elif len(line) < 3 or line[2] != " ":
            results.append(blocked_check("git_checkout", "git_checkout_status_invalid"))
        else:
            if line[0] != " ":
                results.append(blocked_check("index", "index_dirty"))
            if line[1] != " ":
                results.append(blocked_check("tracked_worktree", "tracked_worktree_dirty"))
    facts["untracked_count"] = untracked_count
    results.append(passed_check("untracked_files", count=untracked_count))
    return _finalize_checks(results), facts


class _WheelSnapshotError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _snapshot_wheel(path: Path) -> tuple[io.BytesIO, str]:
    snapshot = io.BytesIO()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            opened_stat = os.fstat(source.fileno())
            attributes = getattr(opened_stat, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if not stat.S_ISREG(opened_stat.st_mode) or bool(attributes & reparse_flag):
                raise _WheelSnapshotError("wheel_not_regular")
            if opened_stat.st_size > MAX_WHEEL_BYTES:
                raise _WheelSnapshotError("wheel_file_too_large")

            total = 0
            while True:
                block = source.read(min(1024 * 1024, MAX_WHEEL_BYTES - total + 1))
                if not block:
                    break
                total += len(block)
                if total > MAX_WHEEL_BYTES:
                    raise _WheelSnapshotError("wheel_file_too_large")
                digest.update(block)
                snapshot.write(block)

            final_stat = os.fstat(source.fileno())
            if total != opened_stat.st_size or final_stat.st_size != opened_stat.st_size:
                raise _WheelSnapshotError("wheel_changed_during_read")
    except _WheelSnapshotError:
        raise
    except OSError as exc:
        raise _WheelSnapshotError("wheel_unavailable") from exc
    snapshot.seek(0)
    return snapshot, digest.hexdigest()


def _is_safe_entry(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    original_name = info.orig_filename
    if (
        not name
        or "\0" in original_name
        or original_name != name
        or "\\" in original_name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
        or (info.is_dir() and info.file_size != 0)
    ):
        return False
    source_parts = original_name.split("/")
    if any(part in {".", ".."} for part in source_parts):
        return False
    if any(not part for part in source_parts[:-1]) or (not info.is_dir() and not source_parts[-1]):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    normalized_name = f"{path}/" if info.is_dir() else str(path)
    if normalized_name != name:
        return False
    if any(part.casefold() in {"models", "outputs"} for part in path.parts):
        return False
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    return file_type in (0, stat.S_IFREG, stat.S_IFDIR)


def _archive_bytes(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_ENTRY_BYTES:
        raise ValueError("entry too large")
    return archive.read(info)


def _contains_sensitive_content(data: bytes) -> bool:
    lowered = data.lower()
    return bool(
        PRIVATE_PATH_RE.search(data)
        or CREDENTIAL_RE.search(data)
        or any(
            marker in lowered
            for marker in (
                b"api_key",
                b"apikey",
            )
        )
    )


def _project_matches(root: Path) -> bool:
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project")
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return False
    return (
        isinstance(project, dict)
        and project.get("name") == "local-gpu-imagegen"
        and project.get("version") == EXPECTED_VERSION
        and project.get("requires-python") == EXPECTED_REQUIRES_PYTHON
        and project.get("dependencies") == []
    )


def _registry_identifier(root: Path) -> str | None:
    try:
        descriptor = json.loads(
            (root / "server.json").read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(descriptor, dict) or descriptor.get("version") != EXPECTED_VERSION:
        return None
    packages = descriptor.get("packages")
    if not isinstance(packages, list) or len(packages) != 1 or not isinstance(packages[0], dict):
        return None
    package = packages[0]
    arguments = package.get("packageArguments")
    transport = package.get("transport")
    if (
        package.get("registryType") != "pypi"
        or package.get("identifier") != "local-gpu-imagegen"
        or package.get("version") != EXPECTED_VERSION
        or package.get("runtimeHint") != "uvx"
        or arguments != [{"type": "positional", "value": "serve"}]
        or transport != {"type": "stdio"}
    ):
        return None
    return "local-gpu-imagegen"


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def inspect_wheel(
    root: Path,
    wheel: Path,
    expected_sha256: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Inspect a built wheel and its checkout descriptors without installing it."""
    if not SHA256_RE.fullmatch(expected_sha256):
        return [blocked_check("candidate_sha256", "candidate_sha256_invalid")], {}
    try:
        wheel_snapshot, actual_sha256 = _snapshot_wheel(wheel)
    except _WheelSnapshotError as exc:
        return [blocked_check("wheel_file", exc.code)], {}
    results: list[dict[str, object]] = []
    facts: dict[str, object] = {"sha256": actual_sha256}
    if wheel.name != EXPECTED_WHEEL:
        results.append(blocked_check("wheel_filename", "wheel_filename_mismatch"))
    else:
        results.append(passed_check("wheel_filename"))
    if actual_sha256 != expected_sha256:
        results.append(blocked_check("wheel_sha256", "wheel_sha256_mismatch"))
    else:
        results.append(passed_check("wheel_sha256"))

    try:
        with wheel_snapshot, zipfile.ZipFile(wheel_snapshot) as archive:
            entries = archive.infolist()
            total_size = sum(info.file_size for info in entries)
            facts["entry_count"] = len(entries)
            facts["uncompressed_bytes"] = total_size
            if (
                len(entries) > MAX_ENTRIES
                or total_size > MAX_TOTAL_BYTES
                or any(info.file_size > MAX_ENTRY_BYTES for info in entries)
            ):
                results.append(blocked_check("wheel_archive", "wheel_archive_too_large"))
                archive_too_large = True
            else:
                results.append(passed_check("wheel_archive", entries=len(entries), bytes=total_size))
                archive_too_large = False

            folded_names = [info.filename.casefold() for info in entries]
            entries_safe = (
                len(folded_names) == len(set(folded_names))
                and all(_is_safe_entry(info) for info in entries)
            )
            if not entries_safe:
                results.append(blocked_check("wheel_entries", "unsafe_wheel_entry"))
            else:
                results.append(passed_check("wheel_entries"))

            names = {info.filename for info in entries}
            duplicates = {name for name, count in Counter(info.filename for info in entries).items() if count > 1}
            dist_roots = {name.split("/", 1)[0] for name in names if ".dist-info/" in name}
            required = {f"{EXPECTED_DIST_INFO}/{item}" for item in ("METADATA", "WHEEL", "RECORD")}
            dist_info_valid = not duplicates and dist_roots == {EXPECTED_DIST_INFO} and required <= names
            if not dist_info_valid:
                results.append(blocked_check("wheel_dist_info", "wheel_dist_info_invalid"))
            else:
                results.append(passed_check("wheel_dist_info"))
            if dist_info_valid and not archive_too_large and entries_safe:
                metadata = BytesParser(policy=default).parsebytes(
                    _archive_bytes(archive, f"{EXPECTED_DIST_INFO}/METADATA")
                )
                wheel_metadata = BytesParser(policy=default).parsebytes(
                    _archive_bytes(archive, f"{EXPECTED_DIST_INFO}/WHEEL")
                )
                if (
                    metadata.defects
                    or wheel_metadata.defects
                    or metadata.get_all("Name") != ["local-gpu-imagegen"]
                    or metadata.get_all("Version") != [EXPECTED_VERSION]
                    or metadata.get_all("Requires-Python") != [EXPECTED_REQUIRES_PYTHON]
                    or metadata.get_all("Requires-Dist")
                    or wheel_metadata.get_all("Wheel-Version") != ["1.0"]
                    or wheel_metadata.get_all("Tag") != ["py3-none-any"]
                ):
                    results.append(blocked_check("wheel_metadata", "wheel_metadata_invalid"))
                else:
                    results.append(passed_check("wheel_metadata", version=EXPECTED_VERSION))

            if archive_too_large or not entries_safe or not dist_info_valid:
                pass
            elif any(_contains_sensitive_content(_archive_bytes(archive, info.filename)) for info in entries if not info.is_dir()):
                results.append(blocked_check("wheel_content", "sensitive_wheel_content"))
            else:
                results.append(passed_check("wheel_content"))
    except (
        OSError,
        EOFError,
        NotImplementedError,
        RuntimeError,
        UnicodeDecodeError,
        ValueError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ):
        results.append(blocked_check("wheel_archive", "wheel_archive_invalid"))

    if _project_matches(root):
        results.append(passed_check("project_metadata"))
    else:
        results.append(blocked_check("project_metadata", "project_metadata_drift"))
    identifier = _registry_identifier(root)
    if identifier is None:
        results.append(blocked_check("registry_descriptor", "registry_descriptor_drift"))
    else:
        facts["registry_identifier"] = identifier
        results.append(passed_check("registry_descriptor", identifier=identifier))
    facts["version"] = EXPECTED_VERSION
    return _finalize_checks(results), facts
