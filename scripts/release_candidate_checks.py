"""Offline static checks for one Local GPU Imagegen release candidate wheel."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
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
EXPECTED_PROTOCOL = "2024-11-05"
PYTHON_VERSION_SCRIPT = "import json,sys; print(json.dumps(list(sys.version_info[:2])))"
CREATE_VENV_SCRIPT = "import sys,venv; venv.EnvBuilder(with_pip=True).create(sys.argv[1])"
EXPECTED_TOOLS = (
    "local_gpu_branch_run",
    "local_gpu_cleanup_run",
    "local_gpu_confirm_mask",
    "local_gpu_discover_models",
    "local_gpu_finalize_run",
    "local_gpu_generate_image",
    "local_gpu_generate_round",
    "local_gpu_get_run",
    "local_gpu_imagegen_check",
    "local_gpu_inspect_workflow",
    "local_gpu_list_profiles",
    "local_gpu_prepare_mask",
    "local_gpu_recommend_models",
    "local_gpu_record_review",
    "local_gpu_register_workflow",
    "local_gpu_set_model_trust",
    "local_gpu_start_run",
)
MAX_ENTRIES = 256
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
# Allows ZIP overhead above the 16 MiB content limit while bounding file I/O.
MAX_WHEEL_BYTES = 32 * 1024 * 1024
PRIVATE_PATH_RE = re.compile(rb"(?i)(?:[a-z]:[\\/]|/(?:home|users)/)")
CREDENTIAL_RE = re.compile(
    rb"(?i)(?:"
    rb"\b(?:authorization|proxy-authorization|x-api-key|api-key)\s*:|"
    rb"\b(?:api[_-]?key|client[_-]?secret|secret[_-]?key|access[_-]?token|"
    rb"refresh[_-]?token|auth[_-]?token|password|passwd|token)\s*[:=]|"
    rb"[\"'](?:client_secret|password|token)[\"']\s*:|"
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


def _snapshot_wheel(path: Path, path_stat: os.stat_result) -> tuple[io.BytesIO, str]:
    snapshot = io.BytesIO()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            opened_stat = os.fstat(source.fileno())
            attributes = getattr(opened_stat, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if not stat.S_ISREG(opened_stat.st_mode) or bool(attributes & reparse_flag):
                raise _WheelSnapshotError("wheel_not_regular")
            if not os.path.samestat(path_stat, opened_stat):
                raise _WheelSnapshotError("wheel_identity_changed")
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
    path_is_directory = name.endswith("/")
    if (
        not name
        or "\0" in original_name
        or original_name != name
        or "\\" in original_name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
        or (path_is_directory and info.file_size != 0)
    ):
        return False
    source_parts = original_name.split("/")
    if any(part in {".", ".."} for part in source_parts):
        return False
    if any(not part for part in source_parts[:-1]) or (not path_is_directory and not source_parts[-1]):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    normalized_name = f"{path}/" if path_is_directory else str(path)
    if normalized_name != name:
        return False
    if any(part.casefold() in {"models", "outputs"} for part in path.parts):
        return False
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if path_is_directory:
        return file_type in (0, stat.S_IFDIR)
    return file_type in (0, stat.S_IFREG)


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
        path_stat = os.lstat(wheel)
    except OSError:
        return [blocked_check("wheel_file", "wheel_unavailable")], {}
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not stat.S_ISREG(path_stat.st_mode) or bool(attributes & reparse_flag):
        return [blocked_check("wheel_file", "wheel_not_regular")], {}
    if path_stat.st_size > MAX_WHEEL_BYTES:
        return [blocked_check("wheel_file", "wheel_file_too_large")], {}

    try:
        wheel_snapshot, actual_sha256 = _snapshot_wheel(wheel, path_stat)
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


class _InstalledCheckError(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _installed_environment(fake_bin: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"):
        environment.pop(name, None)
    environment.update({
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "LOCAL_GPU_IMAGEGEN_WEBUI_URL": "http://127.0.0.1:1",
        "LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "http://127.0.0.1:1",
        "PATH": str(fake_bin) + os.pathsep + environment.get("PATH", ""),
    })
    return environment


def _write_fake_client(directory: Path, name: str, marker: Path) -> None:
    if os.name == "nt":
        script = directory / f"{name}.cmd"
        script.write_text(
            "@echo off\n"
            "if \"%1\"==\"--version\" (echo local test client& exit /b 0)\n"
            "if \"%1\"==\"mcp\" if \"%2\"==\"get\" exit /b 1\n"
            f"if \"%1\"==\"mcp\" if \"%2\"==\"add\" (echo called>\"{marker}\"& exit /b 0)\n"
            "exit /b 2\n",
            encoding="utf-8",
        )
        return
    script = directory / name
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'local test client'; exit 0; fi\n"
        "if [ \"$1\" = \"mcp\" ] && [ \"$2\" = \"get\" ]; then exit 1; fi\n"
        f"if [ \"$1\" = \"mcp\" ] && [ \"$2\" = \"add\" ]; then echo called > '{marker}'; exit 0; fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def _run_json(
    command: list[str], *, cwd: Path, env: dict[str, str], expected_exit: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    try:
        completed = runner(command, cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        raise _InstalledCheckError("execution") from None
    if completed.returncode != expected_exit:
        raise _InstalledCheckError("exit")
    stdout = completed.stdout or ""
    if (not stdout.strip() or len(stdout) > 1024 * 1024
            or "traceback" in (completed.stderr or "").casefold()):
        raise _InstalledCheckError("json")
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        raise _InstalledCheckError("json") from None
    if not isinstance(result, dict):
        raise _InstalledCheckError("json")
    return result


def _python_312_version(
    python: Path,
    *,
    cwd: Path,
    env: dict[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> list[int] | None:
    try:
        completed = runner(
            [str(python), "-c", PYTHON_VERSION_SCRIPT],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    stdout = completed.stdout or ""
    if (
        completed.returncode != 0
        or not stdout.strip()
        or len(stdout) > 1024 * 1024
        or "traceback" in (completed.stderr or "").casefold()
    ):
        return None
    try:
        version = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return version if version == [3, 12] else None


def run_installed_checks(
    wheel: Path, python: Path, *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Verify an already-built wheel from a disposable checkout-external venv."""
    if wheel.name != EXPECTED_WHEEL or not wheel.is_file():
        return [blocked_check("installed_wheel", "installed_wheel_invalid")], {}
    try:
        resolved_wheel = wheel.resolve(strict=True)
    except OSError:
        return [blocked_check("installed_wheel", "installed_wheel_invalid")], {}

    results: list[dict[str, object]] = []
    facts: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        environment_dir = temporary_root / "venv"
        fake_bin = temporary_root / "fake-bin"
        fake_bin.mkdir()
        marker = fake_bin / "client-add-called"
        _write_fake_client(fake_bin, "codex", marker)
        _write_fake_client(fake_bin, "claude", marker)
        environment = _installed_environment(fake_bin)
        version = _python_312_version(
            python,
            cwd=temporary_root,
            env=environment,
            runner=runner,
        )
        if version is None:
            return [blocked_check("release_python", "release_python_312_required")], {}
        facts["release_python_version"] = version
        results.append(passed_check("release_python", version=version))
        try:
            created = runner(
                [str(python), "-c", CREATE_VENV_SCRIPT, str(environment_dir)],
                cwd=temporary_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            results.append(blocked_check("installed_venv", "installed_venv_failed"))
            return _finalize_checks(results), facts
        if created.returncode != 0 or "traceback" in (created.stderr or "").casefold():
            results.append(blocked_check("installed_venv", "installed_venv_failed"))
            return _finalize_checks(results), facts
        installed_python = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = environment_dir / ("Scripts/local-gpu-imagegen.exe" if os.name == "nt" else "bin/local-gpu-imagegen")
        installed_version = _python_312_version(
            installed_python,
            cwd=temporary_root,
            env=environment,
            runner=runner,
        )
        if installed_version is None:
            results.append(blocked_check("installed_venv_python", "release_python_312_required"))
            return _finalize_checks(results), facts
        facts["venv_python_version"] = installed_version
        results.append(passed_check("installed_venv_python", version=installed_version))
        try:
            completed = runner(
                [str(installed_python), "-m", "pip", "install", "--no-index", "--no-deps",
                 "--no-cache-dir", "--disable-pip-version-check", str(resolved_wheel)],
                cwd=temporary_root, env=environment, capture_output=True, text=True,
                timeout=60, check=False,
            )
            if completed.returncode != 0 or "traceback" in (completed.stderr or "").casefold():
                results.append(blocked_check("installed_pip", "installed_pip_install_failed"))
                return _finalize_checks(results), facts
        except (OSError, subprocess.SubprocessError):
            results.append(blocked_check("installed_pip", "installed_pip_install_failed"))
            return _finalize_checks(results), facts

        checks_to_run = (
            ("installed_contract", "installed_contract", [str(cli), "verify"], 0),
            ("installed_doctor", "installed_doctor", [str(cli), "doctor"], 1),
            ("installed_setup_codex", "installed_setup_contract", [str(cli), "setup", "codex"], 0),
            ("installed_setup_claude", "installed_setup_contract", [str(cli), "setup", "claude-code"], 0),
        )
        reports: dict[str, dict[str, object]] = {}
        for check_id, failure_code, command, expected_exit in checks_to_run:
            try:
                reports[check_id] = _run_json(command, cwd=temporary_root, env=environment,
                                              expected_exit=expected_exit, runner=runner)
            except _InstalledCheckError as error:
                code = "installed_json_invalid" if error.kind == "json" else failure_code + "_mismatch"
                results.append(blocked_check(check_id, code))

        verify = reports.get("installed_contract")
        if verify is not None:
            server = verify.get("server")
            if not isinstance(server, dict) or server.get("version") != EXPECTED_VERSION:
                results.append(blocked_check("installed_version", "installed_version_mismatch"))
            else:
                facts["version"] = EXPECTED_VERSION
                results.append(passed_check("installed_version", version=EXPECTED_VERSION))
            if verify.get("protocolVersion") != EXPECTED_PROTOCOL:
                results.append(blocked_check("installed_protocol", "installed_protocol_mismatch"))
            else:
                facts["protocol"] = EXPECTED_PROTOCOL
                results.append(passed_check("installed_protocol", protocol=EXPECTED_PROTOCOL))
            if verify.get("tools") != list(EXPECTED_TOOLS):
                results.append(blocked_check("installed_tools", "installed_tool_contract_mismatch"))
            else:
                facts["tool_count"] = len(EXPECTED_TOOLS)
                facts["tools"] = list(EXPECTED_TOOLS)
                results.append(passed_check("installed_tools", count=len(EXPECTED_TOOLS)))

        doctor = reports.get("installed_doctor")
        if doctor is not None:
            if doctor.get("ready") is not False:
                results.append(blocked_check("installed_doctor", "installed_doctor_mismatch"))
            else:
                facts["doctor_exit"] = 1
                facts["doctor_ready"] = False
                results.append(passed_check("installed_doctor", exit=1, ready=False))
        for check_id, fact_name in (("installed_setup_codex", "codex"), ("installed_setup_claude", "claude")):
            setup = reports.get(check_id)
            if setup is not None:
                if setup.get("status") != "planned" or setup.get("applied") is not False or marker.exists():
                    results.append(blocked_check(check_id, "installed_setup_contract_mismatch"))
                else:
                    facts[f"{fact_name}_dry_run"] = "planned"
                    results.append(passed_check(check_id, status="planned"))

        compile_script = (
            "import compileall,json,local_gpu_imagegen; from pathlib import Path; "
            "root=Path(local_gpu_imagegen.__file__).resolve().parent; sources=list(root.rglob('*.py')); "
            "ok=compileall.compile_dir(str(root), quiet=1); "
            "print(json.dumps({'compiled_sources': len(sources), 'ok': bool(ok)}))"
        )
        try:
            compiled = _run_json([str(installed_python), "-c", compile_script], cwd=temporary_root,
                                 env=environment, expected_exit=0, runner=runner)
            count = compiled.get("compiled_sources")
            if compiled.get("ok") is not True or not isinstance(count, int) or count <= 0:
                raise _InstalledCheckError("contract")
        except _InstalledCheckError:
            results.append(blocked_check("installed_compile", "installed_compile_failed"))
        else:
            facts["compiled_source_count"] = count
            results.append(passed_check("installed_compile", count=count))
    return _finalize_checks(results), facts
