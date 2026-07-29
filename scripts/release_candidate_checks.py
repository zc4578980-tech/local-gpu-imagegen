"""Offline static checks for one Local GPU Imagegen release candidate wheel."""

from __future__ import annotations

import hashlib
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

GitRunner = Callable[..., subprocess.CompletedProcess[str]]


def passed_check(check_id: str, **observation: object) -> dict[str, object]:
    return {"id": check_id, "status": "passed", "observation": observation}


def blocked_check(check_id: str, code: str) -> dict[str, object]:
    return {"id": check_id, "status": "blocked", "code": code}


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


def _untracked_name(status_line: str) -> str:
    name = status_line[3:].strip().replace("\\", "/")
    return name.lstrip("/")


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
        return results, facts

    untracked: list[str] = []
    for line in status.stdout.splitlines():
        if line.startswith("?? "):
            untracked.append(_untracked_name(line))
        elif len(line) < 3 or line[2] != " ":
            results.append(blocked_check("git_checkout", "git_checkout_status_invalid"))
        else:
            if line[0] != " ":
                results.append(blocked_check("index", "index_dirty"))
            if line[1] != " ":
                results.append(blocked_check("tracked_worktree", "tracked_worktree_dirty"))
    facts["untracked_count"] = len(untracked)
    facts["untracked_files"] = untracked[:20]
    results.append(passed_check("untracked_files", count=len(untracked)))
    return results, facts


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_safe_entry(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    original_name = info.orig_filename
    if (
        not name
        or "\\" in original_name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
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
    if any(part in {"models", "outputs"} for part in path.parts):
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
    return any(
        marker in lowered
        for marker in (
            b"c:\\users\\",
            b"/home/",
            b"api_key",
            b"apikey",
            b"authorization:",
            b"bearer ",
            b"token=",
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
        descriptor = json.loads((root / "server.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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


def inspect_wheel(
    root: Path,
    wheel: Path,
    expected_sha256: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Inspect a built wheel and its checkout descriptors without installing it."""
    if not SHA256_RE.fullmatch(expected_sha256):
        return [blocked_check("candidate_sha256", "candidate_sha256_invalid")], {}
    try:
        wheel_stat = os.lstat(wheel)
    except OSError:
        return [blocked_check("wheel_file", "wheel_unavailable")], {}
    attributes = getattr(wheel_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not stat.S_ISREG(wheel_stat.st_mode) or bool(attributes & reparse_flag):
        return [blocked_check("wheel_file", "wheel_not_regular")], {}

    try:
        actual_sha256 = _stream_sha256(wheel)
    except OSError:
        return [blocked_check("wheel_file", "wheel_unavailable")], {}
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
        with zipfile.ZipFile(wheel) as archive:
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

            if any(not _is_safe_entry(info) for info in entries):
                results.append(blocked_check("wheel_entries", "unsafe_wheel_entry"))
            else:
                results.append(passed_check("wheel_entries"))

            names = {info.filename for info in entries}
            duplicates = {name for name, count in Counter(info.filename for info in entries).items() if count > 1}
            dist_roots = {name.split("/", 1)[0] for name in names if ".dist-info/" in name}
            required = {f"{EXPECTED_DIST_INFO}/{item}" for item in ("METADATA", "WHEEL", "RECORD")}
            if duplicates or dist_roots != {EXPECTED_DIST_INFO} or not required <= names:
                results.append(blocked_check("wheel_dist_info", "wheel_dist_info_invalid"))
            elif not archive_too_large:
                metadata = BytesParser(policy=default).parsebytes(
                    _archive_bytes(archive, f"{EXPECTED_DIST_INFO}/METADATA")
                )
                wheel_metadata = BytesParser(policy=default).parsebytes(
                    _archive_bytes(archive, f"{EXPECTED_DIST_INFO}/WHEEL")
                )
                if (
                    metadata.get("Name") != "local-gpu-imagegen"
                    or metadata.get("Version") != EXPECTED_VERSION
                    or metadata.get("Requires-Python") != EXPECTED_REQUIRES_PYTHON
                    or metadata.get_all("Requires-Dist")
                    or wheel_metadata.get("Wheel-Version") != "1.0"
                    or wheel_metadata.get_all("Tag") != ["py3-none-any"]
                ):
                    results.append(blocked_check("wheel_metadata", "wheel_metadata_invalid"))
                else:
                    results.append(passed_check("wheel_metadata", version=EXPECTED_VERSION))

            if archive_too_large:
                pass
            elif any(_contains_sensitive_content(_archive_bytes(archive, info.filename)) for info in entries if not info.is_dir()):
                results.append(blocked_check("wheel_content", "sensitive_wheel_content"))
            else:
                results.append(passed_check("wheel_content"))
    except (OSError, UnicodeDecodeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
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
    return results, facts
