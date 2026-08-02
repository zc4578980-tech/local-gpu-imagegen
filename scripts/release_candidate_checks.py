"""Offline static checks for one Local GPU Imagegen release candidate wheel."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections import Counter
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import Callable, Iterator


SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_WHEEL = "local_gpu_imagegen-0.8.2-py3-none-any.whl"
EXPECTED_VERSION = "0.8.2"
EXPECTED_REQUIRES_PYTHON = ">=3.11"
EXPECTED_DIST_INFO = "local_gpu_imagegen-0.8.2.dist-info"
EXPECTED_PROTOCOL = "2024-11-05"
PUBLIC_MODEL_DESCRIPTOR_PARENT = PurePosixPath(
    "local_gpu_imagegen-0.8.2.data/data/share/local-gpu-imagegen/"
    "profiles/models"
)
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
PRIVATE_PATH_RE = re.compile(
    rb"(?i)(?<![a-z0-9])(?:"
    rb"[a-z]:[\\/][^\\/\s\"']+|/(?:home|users)/[^/\s\"']+|"
    rb"/mnt/[a-z]/users/[^/\s\"']+|"
    rb"\\\\[^\\/\s\"']+[\\/][^\\/\s\"']+[\\/][^\s\"']+"
    rb")"
)
CREDENTIAL_RE = re.compile(
    rb"(?i)(?:\bbearer\s+[^\s\"']{1,512}|"
    rb"\b(?:authorization|proxy-authorization|x-api-key|api-key|"
    rb"api[_-]?key|client[_-]?secret|secret[_-]?key|access[_-]?token|"
    rb"refresh[_-]?token|auth[_-]?token|password|passwd|token)"
    rb"[\"']?\s*[:=]\s*(?:[\"'][^\"'\r\n]{1,512}[\"']|"
    rb"[^\s\"'{\[]{1,512}))"
)
PUBLIC_TOKEN_PREFIXES = frozenset({b"route:"})
SELECTOR_LITERAL_RE = re.compile(rb"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
SAFE_SELECTOR_POSITIONAL_ARGUMENTS = {
    "get": frozenset({0}),
    "getenv": frozenset({0}),
    "set_status": frozenset({1}),
}
SAFE_SELECTOR_KEYWORD_ARGUMENTS = {
    "get": frozenset({"key"}),
    "getenv": frozenset({"key"}),
    "resolve": frozenset({"active_only"}),
    "set_status": frozenset({"status"}),
}
SENSITIVE_CREDENTIAL_KEYS = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "xapikey",
        "apikey",
        "clientsecret",
        "secretkey",
        "accesstoken",
        "refreshtoken",
        "authtoken",
        "password",
        "passwd",
        "token",
    }
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

    status = _run_git(
        runner,
        root,
        "status",
        "--porcelain=v1",
        "--ignored",
        "--untracked-files=all",
    )
    if status is None or status.returncode != 0 or status.stderr.strip():
        results.append(blocked_check("git_checkout", "git_checkout_unavailable"))
        return _finalize_checks(results), facts

    untracked_count = 0
    ignored_count = 0
    for line in status.stdout.splitlines():
        if line.startswith("?? "):
            untracked_count += 1
        elif line.startswith("!! "):
            ignored_count += 1
        elif len(line) < 3 or line[2] != " ":
            results.append(blocked_check("git_checkout", "git_checkout_status_invalid"))
        else:
            if line[0] != " ":
                results.append(blocked_check("index", "index_dirty"))
            if line[1] != " ":
                results.append(blocked_check("tracked_worktree", "tracked_worktree_dirty"))
    facts["untracked_count"] = untracked_count
    facts["ignored_count"] = ignored_count
    results.append(passed_check("ignored_files", count=ignored_count))
    results.append(passed_check("untracked_files", count=untracked_count))
    return _finalize_checks(results), facts


class _WheelSnapshotError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReportCleanupError(OSError):
    """Signal bounded report cleanup failure without exposing OS details."""


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


@contextmanager
def _staged_wheel(path: Path, checkout_root: Path) -> Iterator[tuple[Path, bytes]]:
    """Keep one bounded source snapshot independent from all staged paths."""
    try:
        path_stat = os.lstat(path)
    except OSError as exc:
        raise _WheelSnapshotError("wheel_unavailable") from exc
    if not stat.S_ISREG(path_stat.st_mode) or _is_reparse_point(path_stat):
        raise _WheelSnapshotError("wheel_not_regular")
    if path_stat.st_size > MAX_WHEEL_BYTES:
        raise _WheelSnapshotError("wheel_file_too_large")

    snapshot, _ = _snapshot_wheel(path, path_stat)
    try:
        payload = snapshot.getvalue()
        with tempfile.TemporaryDirectory(prefix="local-gpu-imagegen-candidate-") as temporary:
            staging_root = Path(temporary).resolve(strict=True)
            try:
                staging_root.relative_to(checkout_root.resolve(strict=True))
            except ValueError:
                pass
            except OSError as exc:
                raise _WheelSnapshotError("wheel_staging_unavailable") from exc
            else:
                raise _WheelSnapshotError("wheel_staging_checkout_external_required")

            staging_stat = os.lstat(staging_root)
            if not stat.S_ISDIR(staging_stat.st_mode) or _is_reparse_point(staging_stat):
                raise _WheelSnapshotError("wheel_staging_unavailable")
            staged = staging_root / EXPECTED_WHEEL
            try:
                with staged.open("xb") as target:
                    while True:
                        block = snapshot.read(1024 * 1024)
                        if not block:
                            break
                        target.write(block)
                    target.flush()
                    os.fsync(target.fileno())
            except OSError as exc:
                raise _WheelSnapshotError("wheel_staging_unavailable") from exc
            yield staged, payload
    finally:
        snapshot.close()


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
    if any(part.casefold() == "outputs" for part in path.parts):
        return False
    if any(part.casefold() == "models" for part in path.parts) and not (
        not path_is_directory
        and path.parent == PUBLIC_MODEL_DESCRIPTOR_PARENT
        and path.suffix == ".json"
        and len(path.name) > len(".json")
    ):
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


def _normalized_credential_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _scalar_bytes(value: object) -> bytes | None:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    return None


def _sensitive_scalar(value: object) -> bool:
    encoded = _scalar_bytes(value)
    return bool(
        encoded
        and (PRIVATE_PATH_RE.search(encoded) or CREDENTIAL_RE.search(encoded))
    )


def _credential_target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript):
        return _static_string(target.slice)
    return None


def _call_name(function: ast.expr) -> str | None:
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _expression_contains_literal(
    node: ast.expr,
    *,
    allow_selectors: bool = False,
    allow_public_token_prefix: bool = False,
) -> bool:
    if isinstance(node, ast.Constant):
        encoded = _scalar_bytes(node.value)
        return bool(
            encoded
            and not (allow_selectors and SELECTOR_LITERAL_RE.fullmatch(encoded))
            and not (
                allow_public_token_prefix and encoded in PUBLIC_TOKEN_PREFIXES
            )
        )
    if isinstance(node, ast.Subscript):
        selector_value = _static_string(node.slice)
        selector = _scalar_bytes(selector_value)
        unsafe_selector = selector is None or not SELECTOR_LITERAL_RE.fullmatch(
            selector
        )
        return _expression_contains_literal(
            node.value,
            allow_selectors=allow_selectors,
            allow_public_token_prefix=allow_public_token_prefix,
        ) or (
            unsafe_selector and _expression_contains_literal(node.slice)
        )
    if isinstance(node, ast.Call):
        call_name = _call_name(node.func)
        safe_positions = SAFE_SELECTOR_POSITIONAL_ARGUMENTS.get(
            call_name or "", frozenset()
        )
        safe_keywords = SAFE_SELECTOR_KEYWORD_ARGUMENTS.get(
            call_name or "", frozenset()
        )
        return (
            isinstance(node.func, ast.Attribute)
            and _expression_contains_literal(
                node.func.value,
                allow_selectors=allow_selectors,
                allow_public_token_prefix=allow_public_token_prefix,
            )
        ) or any(
            _expression_contains_literal(
                argument,
                allow_selectors=index in safe_positions,
                allow_public_token_prefix=allow_public_token_prefix,
            )
            for index, argument in enumerate(node.args)
        ) or any(
            _expression_contains_literal(
                keyword.value,
                allow_selectors=keyword.arg in safe_keywords,
                allow_public_token_prefix=allow_public_token_prefix,
            )
            for keyword in node.keywords
        )
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Constant):
            encoded = _scalar_bytes(child.value)
            if allow_public_token_prefix and encoded in PUBLIC_TOKEN_PREFIXES:
                continue
        if _expression_contains_literal(
            child,
            allow_selectors=allow_selectors,
            allow_public_token_prefix=allow_public_token_prefix,
        ):
            return True
    return False


def _static_string_sequence(node: ast.expr) -> list[str] | None:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values: list[str] = []
    total_length = 0
    for element in node.elts:
        value = _static_string(element)
        if value is None:
            return None
        values.append(value)
        total_length += len(value)
        if total_length > 512:
            return None
    return values


def _static_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if len(node.value) <= 512 else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        if (
            left is not None
            and right is not None
            and len(left) + len(right) <= 512
        ):
            return left + right
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        template = _static_string(node.left)
        if (
            template is None
            or re.fullmatch(r"(?:[^%]|%%|%s)*", template) is None
        ):
            return None
        sequence = _static_string_sequence(node.right)
        scalar = _static_string(node.right) if sequence is None else None
        if sequence is None and scalar is None:
            return None
        try:
            operand = tuple(sequence) if sequence is not None else scalar
            result = template % operand
        except (TypeError, ValueError):
            return None
        return result if len(result) <= 512 else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        total_length = 0
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                part = value.value
            elif (
                isinstance(value, ast.FormattedValue)
                and value.conversion in (-1, ord("s"))
            ):
                part = _static_string(value.value)
                if part is None:
                    return None
                format_spec = (
                    _static_string(value.format_spec)
                    if value.format_spec is not None
                    else ""
                )
                if format_spec not in ("", "s"):
                    return None
            else:
                return None
            parts.append(part)
            total_length += len(part)
            if total_length > 512:
                return None
        return "".join(parts)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        template = _static_string(node.func.value)
        positional = [_static_string(argument) for argument in node.args]
        keywords = {
            keyword.arg: _static_string(keyword.value)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        if (
            template is None
            or any(argument is None for argument in positional)
            or len(keywords) != len(node.keywords)
            or any(argument is None for argument in keywords.values())
        ):
            return None
        parts: list[str] = []
        total_length = 0
        automatic_index = 0
        try:
            fields = Formatter().parse(template)
            for literal, field_name, format_spec, conversion in fields:
                parts.append(literal)
                total_length += len(literal)
                if total_length > 512:
                    return None
                if field_name is None:
                    continue
                if format_spec not in ("", "s") or conversion not in (None, "s"):
                    return None
                if field_name == "":
                    index = automatic_index
                    automatic_index += 1
                    argument = (
                        positional[index] if index < len(positional) else None
                    )
                elif field_name.isdecimal():
                    index = int(field_name)
                    argument = (
                        positional[index] if index < len(positional) else None
                    )
                elif field_name.isidentifier():
                    argument = keywords.get(field_name)
                else:
                    return None
                if argument is None:
                    return None
                parts.append(argument)
                total_length += len(argument)
                if total_length > 512:
                    return None
        except ValueError:
            return None
        result = "".join(parts)
        return result if len(result) <= 512 else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and not node.keywords
    ):
        separator = _static_string(node.func.value)
        values = _static_string_sequence(node.args[0])
        if separator is None or values is None:
            return None
        result = separator.join(values)
        return result if len(result) <= 512 else None
    return None


def _credential_binding_contains_literal(target: ast.expr, value: ast.expr) -> bool:
    if isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(target.elts) == len(value.elts):
            return any(
                _credential_binding_contains_literal(child_target, child_value)
                for child_target, child_value in zip(target.elts, value.elts)
            )
        return any(
            _credential_target_name(child) is not None
            and _normalized_credential_key(_credential_target_name(child) or "")
            in SENSITIVE_CREDENTIAL_KEYS
            for child in ast.walk(target)
        ) and _expression_contains_literal(value)
    name = _credential_target_name(target)
    normalized_name = _normalized_credential_key(name) if name is not None else None
    return bool(
        normalized_name in SENSITIVE_CREDENTIAL_KEYS
        and _expression_contains_literal(
            value,
            allow_public_token_prefix=normalized_name == "token",
        )
    )


def _arguments_contain_sensitive_defaults(arguments: ast.arguments) -> bool:
    positional = [*arguments.posonlyargs, *arguments.args]
    positional_defaults = zip(positional[-len(arguments.defaults):], arguments.defaults)
    keyword_defaults = zip(arguments.kwonlyargs, arguments.kw_defaults)
    return any(
        default is not None
        and _normalized_credential_key(argument.arg) in SENSITIVE_CREDENTIAL_KEYS
        and _expression_contains_literal(default)
        for argument, default in (*positional_defaults, *keyword_defaults)
    )


def _python_contains_sensitive_content(data: bytes) -> bool:
    try:
        tree = ast.parse(data.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and _sensitive_scalar(node.value):
            return True
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                key_value = _static_string(key) if key is not None else None
                if (
                    key_value is not None
                    and _normalized_credential_key(key_value)
                    in SENSITIVE_CREDENTIAL_KEYS
                    and _expression_contains_literal(value)
                ):
                    return True
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg is not None
                    and _normalized_credential_key(keyword.arg)
                    in SENSITIVE_CREDENTIAL_KEYS
                    and _expression_contains_literal(keyword.value)
                ):
                    return True
        if isinstance(node, ast.ClassDef):
            for keyword in node.keywords:
                if (
                    keyword.arg is not None
                    and _normalized_credential_key(keyword.arg)
                    in SENSITIVE_CREDENTIAL_KEYS
                    and _expression_contains_literal(keyword.value)
                ):
                    return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if _arguments_contain_sensitive_defaults(node.args):
                return True
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None and any(
                _credential_binding_contains_literal(target, value)
                for target in targets
            ):
                return True
        if isinstance(node, ast.AugAssign) and _credential_binding_contains_literal(
            node.target, node.value
        ):
            return True
    return False


def _json_sensitive_binding_contains_value(value: object) -> bool:
    if isinstance(value, list):
        return any(
            _json_sensitive_binding_contains_value(item)
            if isinstance(item, (dict, list))
            else item not in (None, "")
            for item in value
        )
    if not isinstance(value, dict):
        return value not in (None, "")
    for key, child in value.items():
        normalized_key = (
            _normalized_credential_key(key) if isinstance(key, str) else None
        )
        if normalized_key in {"const", "default", "value"} and child not in (
            None,
            "",
            [],
            {},
        ):
            return True
        if normalized_key in SENSITIVE_CREDENTIAL_KEYS:
            if _json_sensitive_binding_contains_value(child):
                return True
        elif isinstance(child, (dict, list)):
            if _json_sensitive_binding_contains_value(child):
                return True
    return False


def _json_contains_sensitive_content(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _sensitive_scalar(key):
                return True
            if (
                isinstance(key, str)
                and _normalized_credential_key(key) in SENSITIVE_CREDENTIAL_KEYS
                and _json_sensitive_binding_contains_value(child)
            ):
                return True
            if _json_contains_sensitive_content(child):
                return True
        return False
    if isinstance(value, list):
        return any(_json_contains_sensitive_content(item) for item in value)
    return _sensitive_scalar(value)


def _contains_sensitive_content(data: bytes, name: str) -> bool:
    suffix = PurePosixPath(name).suffix.casefold()
    if suffix == ".py":
        return _python_contains_sensitive_content(data)
    if suffix == ".json":
        try:
            value = json.loads(data, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return True
        return _json_contains_sensitive_content(value)
    return bool(PRIVATE_PATH_RE.search(data) or CREDENTIAL_RE.search(data))


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
    facts: dict[str, object] = {
        "filename": wheel.name,
        "sha256": actual_sha256,
        "size_bytes": path_stat.st_size,
    }
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
            elif any(
                _contains_sensitive_content(
                    _archive_bytes(archive, info.filename), info.filename
                )
                for info in entries
                if not info.is_dir()
            ):
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
    for name in list(environment):
        if name.casefold().endswith("_proxy"):
            environment.pop(name, None)
    environment.update({
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "LOCAL_GPU_IMAGEGEN_WEBUI_URL": "http://127.0.0.1:1",
        "LOCAL_GPU_IMAGEGEN_COMFYUI_URL": "http://127.0.0.1:1",
        "NO_PROXY": "*",
        "no_proxy": "*",
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


@contextmanager
def _materialized_install_wheel(
    temporary_root: Path, payload: bytes,
) -> Iterator[tuple[Path, dict[str, object]]]:
    wheel_root = temporary_root / "wheel-input"
    wheel_root.mkdir(mode=0o700)
    wheel_path = wheel_root / EXPECTED_WHEEL
    parent_stat = os.lstat(wheel_root)
    if os.name == "nt":
        parent_descriptor = _windows_open_parent(wheel_root, parent_stat)
        try:
            descriptor = _windows_open_locked_file(wheel_path, delete_access=False)
        except BaseException:
            os.close(parent_descriptor)
            raise
        install_path = wheel_path
        runner_options: dict[str, object] = {}
    elif sys.platform.startswith("linux"):
        parent_descriptor = os.open(
            wheel_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            descriptor = os.open(
                EXPECTED_WHEEL,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
        except BaseException:
            os.close(parent_descriptor)
            raise
        install_path = Path(f"/proc/self/fd/{parent_descriptor}/{EXPECTED_WHEEL}")
        runner_options = {"pass_fds": (parent_descriptor,)}
    else:
        raise OSError("immutable wheel install unsupported")

    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        _verify_descriptor_bytes(descriptor, payload)
        if sys.platform.startswith("linux"):
            os.fchmod(descriptor, 0o400)
            os.chmod(wheel_root, 0o500)
        yield install_path, runner_options
    finally:
        cleanup_failed = False
        for open_descriptor in (descriptor, parent_descriptor):
            try:
                os.close(open_descriptor)
            except OSError:
                cleanup_failed = True
        if sys.platform.startswith("linux"):
            try:
                os.chmod(wheel_root, 0o700)
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            raise OSError("installed wheel cleanup failed")


def run_installed_checks(
    wheel: Path, python: Path, *,
    wheel_payload: bytes | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Verify an already-built wheel from a disposable checkout-external venv."""
    if wheel.name != EXPECTED_WHEEL:
        return [blocked_check("installed_wheel", "installed_wheel_invalid")], {}
    if wheel_payload is None:
        try:
            wheel_stat = os.lstat(wheel)
            if not stat.S_ISREG(wheel_stat.st_mode) or _is_reparse_point(wheel_stat):
                raise _WheelSnapshotError("installed_wheel_invalid")
            snapshot, _ = _snapshot_wheel(wheel, wheel_stat)
            try:
                wheel_payload = snapshot.getvalue()
            finally:
                snapshot.close()
        except (OSError, _WheelSnapshotError):
            return [blocked_check("installed_wheel", "installed_wheel_invalid")], {}
    elif type(wheel_payload) is not bytes or len(wheel_payload) > MAX_WHEEL_BYTES:
        return [blocked_check("installed_wheel", "installed_wheel_invalid")], {}

    results: list[dict[str, object]] = []
    facts: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as temporary_directory:
        try:
            temporary_root = Path(temporary_directory).resolve(strict=True)
            checkout_root = Path(__file__).resolve().parents[1]
            temporary_root.relative_to(checkout_root)
        except ValueError:
            pass
        except OSError:
            return [blocked_check("installed_environment", "installed_checkout_external_required")], {}
        else:
            return [blocked_check("installed_environment", "installed_checkout_external_required")], {}
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
        results.append(passed_check("installed_venv"))
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
            with _materialized_install_wheel(
                temporary_root, wheel_payload
            ) as (install_wheel, runner_options):
                wheel_digest = hashlib.sha256(wheel_payload).hexdigest()
                wheel_reference = (
                    f"{install_wheel.as_uri()}#sha256={wheel_digest}"
                )
                completed = runner(
                    [str(installed_python), "-m", "pip", "install", "--no-index", "--no-deps",
                     "--no-cache-dir", "--disable-pip-version-check", "--require-hashes",
                     wheel_reference],
                    cwd=temporary_root, env=environment, capture_output=True, text=True,
                    timeout=60, check=False, **runner_options,
                )
            if completed.returncode != 0 or "traceback" in (completed.stderr or "").casefold():
                results.append(blocked_check("installed_pip", "installed_pip_install_failed"))
                return _finalize_checks(results), facts
        except (OSError, subprocess.SubprocessError):
            results.append(blocked_check("installed_pip", "installed_pip_install_failed"))
            return _finalize_checks(results), facts
        results.append(passed_check("installed_pip"))

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
            else:
                if check_id == "installed_contract":
                    results.append(passed_check(check_id))

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
            if compiled.get("ok") is not True or type(count) is not int or count <= 0:
                raise _InstalledCheckError("contract")
        except _InstalledCheckError:
            results.append(blocked_check("installed_compile", "installed_compile_failed"))
        else:
            facts["compiled_source_count"] = count
            results.append(passed_check("installed_compile", count=count))
    return _finalize_checks(results), facts


def canonical_report(report: dict[str, object]) -> bytes:
    """Encode a stable report that is safe to compare or persist verbatim."""
    return (
        json.dumps(
            report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
        )
        + "\n"
    ).encode("ascii")


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _safe_report_parent(
    destination: Path,
) -> tuple[Path, os.stat_result, os.stat_result | None]:
    parent = destination.parent
    if destination.name in {"", ".", ".."}:
        raise ValueError("unsafe report destination")
    try:
        parent_stat = os.lstat(parent)
    except OSError as error:
        raise ValueError("unsafe report parent") from error
    if not stat.S_ISDIR(parent_stat.st_mode) or _is_reparse_point(parent_stat):
        raise ValueError("unsafe report parent")
    try:
        destination_stat = os.lstat(destination)
    except FileNotFoundError:
        return parent, parent_stat, None
    except OSError as error:
        raise ValueError("unsafe report destination") from error
    if not stat.S_ISREG(destination_stat.st_mode) or _is_reparse_point(destination_stat):
        raise ValueError("unsafe report destination")
    return parent, parent_stat, destination_stat


def _write_all(descriptor: int, encoded: bytes) -> None:
    written = 0
    while written < len(encoded):
        count = os.write(descriptor, encoded[written:])
        if count <= 0:
            raise OSError("report write failed")
        written += count


def _verify_descriptor_bytes(descriptor: int, encoded: bytes) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    observed = bytearray()
    while len(observed) <= len(encoded):
        block = os.read(descriptor, min(1024 * 1024, len(encoded) - len(observed) + 1))
        if not block:
            break
        observed.extend(block)
    if bytes(observed) != encoded:
        raise OSError("report verification failed")


def _windows_file_api() -> tuple[object, object, object]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    return create_file, set_information, close_handle


def _windows_open_parent(parent: Path, expected: os.stat_result) -> int:
    import ctypes
    import msvcrt

    create_file, _, close_handle = _windows_file_api()
    handle = create_file(
        str(parent),
        0x0001 | 0x00100000,
        0x0001 | 0x0002,
        None,
        3,
        0x02000000,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
    except BaseException:
        close_handle(handle)
        raise
    try:
        if not os.path.samestat(os.fstat(descriptor), expected):
            raise ValueError("unsafe report parent")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _windows_open_locked_file(path: Path, *, delete_access: bool = True) -> int:
    import ctypes
    import msvcrt

    create_file, _, close_handle = _windows_file_api()
    handle = create_file(
        str(path),
        0x80000000 | 0x40000000 | (0x00010000 if delete_access else 0),
        0x0001,
        None,
        1,
        0x00000080,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDWR | os.O_BINARY)
    except BaseException:
        close_handle(handle)
        raise


def _windows_open_pending(parent: Path) -> int:
    for _ in range(32):
        pending = parent / f".release-candidate-{secrets.token_hex(16)}.pending"
        try:
            return _windows_open_locked_file(pending)
        except OSError as error:
            if getattr(error, "winerror", None) not in {80, 183}:
                raise
    raise OSError("report pending creation failed")


def _windows_dispose_pending(descriptor: int) -> None:
    import ctypes
    import msvcrt

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", ctypes.c_ubyte)]

    _, set_information, _ = _windows_file_api()
    disposition = FileDispositionInfo(1)
    if not set_information(
        msvcrt.get_osfhandle(descriptor),
        4,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise OSError("report pending cleanup failed")


def _windows_commit_report(descriptor: int, destination: Path) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    destination_text = str(destination)

    class FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * (len(destination_text) + 1)),
        ]

    _, set_information, _ = _windows_file_api()
    rename = FileRenameInfo()
    rename.ReplaceIfExists = 0
    rename.RootDirectory = None
    rename.FileNameLength = len(destination_text.encode("utf-16-le"))
    rename.FileName = destination_text
    if not set_information(
        msvcrt.get_osfhandle(descriptor),
        3,
        ctypes.byref(rename),
        ctypes.sizeof(rename),
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def _linux_open_pending(parent_descriptor: int) -> int:
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_TMPFILE", 0)
    if not getattr(os, "O_TMPFILE", 0):
        raise OSError("atomic report install unsupported")
    return os.open(".", flags, 0o600, dir_fd=parent_descriptor)


def _linux_commit_report(descriptor: int, parent_descriptor: int, name: str) -> None:
    import ctypes

    library = ctypes.CDLL(None, use_errno=True)
    linkat = library.linkat
    linkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    linkat.restype = ctypes.c_int
    if linkat(descriptor, b"", parent_descriptor, os.fsencode(name), 0x1000) != 0:
        error = ctypes.get_errno()
        raise OSError(error, "atomic report install failed")


def _commit_report_install_if_absent(
    descriptor: int, parent_descriptor: int, destination: Path
) -> None:
    if os.name == "nt":
        _windows_commit_report(descriptor, destination)
    elif sys.platform.startswith("linux"):
        _linux_commit_report(descriptor, parent_descriptor, destination.name)
    else:
        raise OSError("atomic report install unsupported")


def _report_parent_is_bound(
    parent: Path, parent_descriptor: int, expected: os.stat_result,
) -> bool:
    try:
        current_path = os.lstat(parent)
        current_handle = os.fstat(parent_descriptor)
        return (
            stat.S_ISDIR(current_path.st_mode)
            and not _is_reparse_point(current_path)
            and os.path.samestat(current_path, current_handle)
            and os.path.samestat(current_handle, expected)
        )
    except OSError:
        return False


def _report_commit_is_visible(
    descriptor: int, parent_descriptor: int, destination: Path,
) -> bool:
    try:
        if os.name == "nt":
            destination_stat = os.lstat(destination)
        else:
            destination_stat = os.stat(
                destination.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        return (
            stat.S_ISREG(destination_stat.st_mode)
            and not _is_reparse_point(destination_stat)
            and os.path.samestat(os.fstat(descriptor), destination_stat)
        )
    except OSError:
        return False


def _remove_linux_committed_report(
    descriptor: int, parent_descriptor: int, name: str,
) -> None:
    try:
        destination_stat = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
        if not os.path.samestat(os.fstat(descriptor), destination_stat):
            raise ReportCleanupError("report cleanup identity mismatch")
        os.unlink(name, dir_fd=parent_descriptor)
    except ReportCleanupError:
        raise
    except OSError as error:
        raise ReportCleanupError("report cleanup failed") from error


def atomic_write_report(destination: Path, encoded: bytes) -> None:
    """Atomically install one complete report without replacing an existing file."""
    destination = Path(destination)
    parent, parent_stat, destination_stat = _safe_report_parent(destination)
    if destination_stat is not None:
        raise FileExistsError("report destination already exists")
    try:
        resolved_parent = parent.resolve(strict=True)
    except OSError as error:
        raise ValueError("unsafe report parent") from error
    resolved_destination = resolved_parent / destination.name

    if os.name == "nt":
        parent_descriptor = _windows_open_parent(resolved_parent, parent_stat)
        try:
            descriptor = _windows_open_pending(resolved_parent)
        except BaseException:
            os.close(parent_descriptor)
            raise
    elif sys.platform.startswith("linux"):
        parent_descriptor = os.open(
            resolved_parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            if not os.path.samestat(os.fstat(parent_descriptor), parent_stat):
                raise ValueError("unsafe report parent")
            descriptor = _linux_open_pending(parent_descriptor)
        except BaseException:
            os.close(parent_descriptor)
            raise
    else:
        raise OSError("atomic report install unsupported")

    committed = False
    windows_disposed = False
    cleanup_error: ReportCleanupError | None = None
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
        _verify_descriptor_bytes(descriptor, encoded)
        if sys.platform.startswith("linux"):
            os.fchmod(descriptor, 0o400)
        if not _report_parent_is_bound(
            resolved_parent, parent_descriptor, parent_stat
        ):
            raise ValueError("unsafe report parent")
        try:
            _commit_report_install_if_absent(
                descriptor, parent_descriptor, resolved_destination
            )
        except BaseException:
            if _report_commit_is_visible(
                descriptor, parent_descriptor, resolved_destination
            ):
                committed = True
            else:
                raise
        else:
            committed = True
        if committed and not _report_parent_is_bound(
            resolved_parent, parent_descriptor, parent_stat
        ):
            if os.name == "nt":
                try:
                    _windows_dispose_pending(descriptor)
                    windows_disposed = True
                except OSError:
                    cleanup_error = ReportCleanupError(
                        "report committed cleanup failed"
                    )
                else:
                    committed = False
            elif sys.platform.startswith("linux"):
                _remove_linux_committed_report(
                    descriptor, parent_descriptor, resolved_destination.name
                )
                committed = False
            if cleanup_error is not None:
                raise cleanup_error
            raise ValueError("unsafe report parent")
    finally:
        if not committed and os.name == "nt" and not windows_disposed:
            try:
                _windows_dispose_pending(descriptor)
            except OSError:
                cleanup_error = ReportCleanupError("report pending cleanup failed")
        for open_descriptor in (descriptor, parent_descriptor):
            try:
                os.close(open_descriptor)
            except OSError:
                if not committed:
                    cleanup_error = cleanup_error or ReportCleanupError(
                        "report handle cleanup failed"
                    )
        if cleanup_error is not None:
            raise cleanup_error


def _inspect_release_python(python: Path) -> list[dict[str, object]]:
    try:
        python_stat = os.lstat(python)
    except OSError:
        return [blocked_check("candidate_python", "candidate_python_unavailable")]
    if not stat.S_ISREG(python_stat.st_mode) or _is_reparse_point(python_stat):
        return [blocked_check("candidate_python", "candidate_python_not_regular")]
    return [passed_check("candidate_python")]


def _all_checks_passed(checks: list[dict[str, object]]) -> bool:
    return bool(checks) and all(check.get("status") == "passed" for check in checks)


def _blocked_candidate_report(checks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "blocked",
        "candidate": None,
        "checks": _finalize_checks(checks),
        "next_action": "fix_candidate_validation_and_rerun",
    }


def _candidate_summary(
    checkout_facts: dict[str, object],
    wheel_facts: dict[str, object],
    installed_facts: dict[str, object],
) -> dict[str, object]:
    candidate: dict[str, object] = {}
    commit = checkout_facts.get("commit")
    if isinstance(commit, str) and SHA1_RE.fullmatch(commit):
        candidate["commit"] = commit
    digest = wheel_facts.get("sha256")
    if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
        candidate["wheel_sha256"] = digest
    if wheel_facts.get("filename") == EXPECTED_WHEEL:
        candidate["wheel_name"] = EXPECTED_WHEEL
    size_bytes = wheel_facts.get("size_bytes")
    if type(size_bytes) is int and 0 <= size_bytes <= MAX_WHEEL_BYTES:
        candidate["wheel_size_bytes"] = size_bytes
    if wheel_facts.get("version") == EXPECTED_VERSION:
        candidate["version"] = EXPECTED_VERSION
    if installed_facts.get("protocol") == EXPECTED_PROTOCOL:
        candidate["protocol"] = EXPECTED_PROTOCOL
    if installed_facts.get("tool_count") == len(EXPECTED_TOOLS):
        candidate["tool_count"] = len(EXPECTED_TOOLS)
    return candidate


_RUNTIME_CODES = frozenset(
    {"candidate_report_cleanup_failed", "candidate_validation_failed"}
)


def blocked_runtime_report(code: str) -> dict[str, object]:
    safe_code = code if code in _RUNTIME_CODES else "candidate_validation_failed"
    return {
        "schema_version": "1.0",
        "status": "blocked",
        "candidate": None,
        "checks": [blocked_check("runtime", safe_code)],
        "next_action": "fix_candidate_validation_and_rerun",
    }


def validate_candidate(
    *,
    root: Path,
    wheel: Path,
    expected_commit: str,
    expected_wheel_sha256: str,
    python: Path,
) -> dict[str, object]:
    """Validate one local wheel without building, downloading, or publishing."""
    try:
        checkout_checks, checkout_facts = inspect_checkout(root, expected_commit)
        python_checks = _inspect_release_python(python)
    except (OSError, ValueError, subprocess.SubprocessError):
        return blocked_runtime_report("candidate_validation_failed")

    if not SHA256_RE.fullmatch(expected_wheel_sha256):
        return _blocked_candidate_report(
            checkout_checks
            + python_checks
            + [blocked_check("candidate_sha256", "candidate_sha256_invalid")]
        )
    if wheel.name != EXPECTED_WHEEL:
        return _blocked_candidate_report(
            checkout_checks
            + python_checks
            + [blocked_check("wheel_filename", "wheel_filename_mismatch")]
        )

    try:
        with _staged_wheel(wheel, root) as (staged_wheel, wheel_payload):
            wheel_checks, wheel_facts = inspect_wheel(
                root, staged_wheel, expected_wheel_sha256
            )
            static_checks = _finalize_checks(
                checkout_checks + wheel_checks + python_checks
            )
            if not _all_checks_passed(static_checks):
                return _blocked_candidate_report(static_checks)
            installed_checks, installed_facts = run_installed_checks(
                staged_wheel, python, wheel_payload=wheel_payload
            )
    except _WheelSnapshotError as error:
        return _blocked_candidate_report(
            checkout_checks
            + python_checks
            + [blocked_check("wheel_file", error.code)]
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return blocked_runtime_report("candidate_validation_failed")
    all_checks = _finalize_checks(static_checks + installed_checks)
    passed = _all_checks_passed(all_checks)
    return {
        "schema_version": "1.0",
        "status": "passed" if passed else "blocked",
        "candidate": _candidate_summary(checkout_facts, wheel_facts, installed_facts),
        "checks": all_checks,
        "next_action": (
            "ready_for_separate_publication_authorization"
            if passed
            else "fix_candidate_validation_and_rerun"
        ),
    }
