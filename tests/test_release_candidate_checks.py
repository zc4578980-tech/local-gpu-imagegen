from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_candidate_checks as checks


class ReleaseCandidateStaticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="release-candidate-checks-"))

    def tearDown(self) -> None:
        def remove_readonly(func: object, path: str, _: object) -> None:
            os.chmod(path, stat.S_IWRITE)
            func(path)  # type: ignore[operator]

        shutil.rmtree(self.temp, onerror=remove_readonly)

    def make_git_checkout(self) -> tuple[Path, str]:
        root = self.temp / f"checkout-{uuid.uuid4().hex}"
        root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=root,
            check=True,
        )
        (root / "tracked.txt").write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        return root, commit

    @staticmethod
    def codes(results: list[dict[str, object]]) -> set[str]:
        return {str(item["code"]) for item in results if "code" in item}

    @staticmethod
    def blocked_ids(results: list[dict[str, object]]) -> set[str]:
        return {str(item["id"]) for item in results if item["status"] == "blocked"}

    def assert_result_contract(self, results: list[dict[str, object]]) -> None:
        ids = [str(item["id"]) for item in results]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_checkout_requires_exact_head_and_clean_tracked_state(self) -> None:
        root, commit = self.make_git_checkout()
        results, facts = checks.inspect_checkout(root, commit)
        self.assertTrue(all(item["status"] == "passed" for item in results))
        self.assertEqual(facts["commit"], commit)

        (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        failed, _ = checks.inspect_checkout(root, commit)
        self.assertIn("tracked_worktree_dirty", self.codes(failed))

        staged = self.make_git_checkout()
        (staged[0] / "tracked.txt").write_text("staged\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=staged[0], check=True)
        failed, _ = checks.inspect_checkout(*staged)
        self.assertIn("index_dirty", self.codes(failed))

    def test_checkout_rejects_non_lowercase_or_mismatched_commit(self) -> None:
        root, commit = self.make_git_checkout()
        malformed, _ = checks.inspect_checkout(root, commit.upper())
        self.assertIn("candidate_commit_invalid", self.codes(malformed))
        mismatched, _ = checks.inspect_checkout(root, "0" * 40)
        self.assertIn("candidate_commit_mismatch", self.codes(mismatched))

    def test_checkout_reports_untracked_without_blocking(self) -> None:
        root, commit = self.make_git_checkout()
        (root / ".codex").mkdir()
        (root / ".codex" / "config.toml").write_text("local = true\n", encoding="utf-8")
        results, facts = checks.inspect_checkout(root, commit)
        self.assertNotIn("untracked_files", self.blocked_ids(results))
        self.assertEqual(facts["untracked_count"], 1)

    def test_checkout_bounds_untracked_names_and_runner_failure(self) -> None:
        root, commit = self.make_git_checkout()
        for number in range(24):
            (root / f"untracked-{number:02}.txt").write_text("x", encoding="utf-8")
        _, facts = checks.inspect_checkout(root, commit)
        self.assertEqual(facts["untracked_count"], 24)
        self.assertNotIn("untracked_files", facts)

        def unavailable(_: Path, *args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 1, "", "not a repository")

        results, _ = checks.inspect_checkout(root, commit, runner=unavailable)
        self.assertIn("git_checkout_unavailable", self.codes(results))

    def test_checkout_does_not_expose_untracked_names(self) -> None:
        root, commit = self.make_git_checkout()
        private_name = "models/private-run.safetensors"
        (root / "models").mkdir()
        (root / private_name).write_text("private", encoding="utf-8")
        _, facts = checks.inspect_checkout(root, commit)
        self.assertEqual(facts["untracked_count"], 1)
        self.assertNotIn("untracked_files", facts)
        self.assertNotIn(private_name, str(facts))

    def test_checkout_blocks_porcelain_tracked_state_and_runner_exception(self) -> None:
        root, commit = self.make_git_checkout()

        def porcelain_dirty(_: Path, *args: str) -> subprocess.CompletedProcess[str]:
            if args == ("rev-parse", "HEAD"):
                return subprocess.CompletedProcess(["git", *args], 0, commit + "\n", "")
            if args == ("status", "--porcelain=v1"):
                return subprocess.CompletedProcess(["git", *args], 0, " M tracked.txt\n", "")
            return subprocess.CompletedProcess(["git", *args], 0, "", "")

        results, _ = checks.inspect_checkout(root, commit, runner=porcelain_dirty)
        self.assertIn("tracked_worktree_dirty", self.codes(results))

        def raises(_: Path, *args: str) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("git unavailable")

        results, _ = checks.inspect_checkout(root, commit, runner=raises)
        self.assertEqual(self.codes(results), {"git_checkout_unavailable"})

    def test_checkout_returns_sorted_unique_non_contradictory_checks(self) -> None:
        root, commit = self.make_git_checkout()

        def dirty(_: Path, *args: str) -> subprocess.CompletedProcess[str]:
            if args == ("rev-parse", "HEAD"):
                return subprocess.CompletedProcess(["git", *args], 0, commit + "\n", "")
            if args == ("diff", "--quiet") or args == ("diff", "--cached", "--quiet"):
                return subprocess.CompletedProcess(["git", *args], 1, "", "")
            if args == ("status", "--porcelain=v1"):
                return subprocess.CompletedProcess(["git", *args], 0, "MM tracked.txt\n", "")
            raise AssertionError(args)

        results, _ = checks.inspect_checkout(root, commit, runner=dirty)
        self.assert_result_contract(results)
        self.assertEqual(
            [item["status"] for item in results if item["id"] in {"index", "tracked_worktree"}],
            ["blocked", "blocked"],
        )

    def test_test_teardown_uses_python_311_rmtree_api(self) -> None:
        teardown_source = inspect.getsource(ReleaseCandidateStaticTests.tearDown)
        self.assertNotIn("onexc", teardown_source)
        self.assertIn("onerror", teardown_source)


class ReleaseCandidateWheelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="release-candidate-wheel-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    @staticmethod
    def codes(results: list[dict[str, object]]) -> set[str]:
        return {str(item["code"]) for item in results if "code" in item}

    @staticmethod
    def blocked_ids(results: list[dict[str, object]]) -> set[str]:
        return {str(item["id"]) for item in results if item["status"] == "blocked"}

    def assert_result_contract(self, results: list[dict[str, object]]) -> None:
        ids = [str(item["id"]) for item in results]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def make_release_root(self) -> Path:
        root = self.temp / f"release-{uuid.uuid4().hex}"
        root.mkdir()
        shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
        shutil.copy2(ROOT / "server.json", root / "server.json")
        return root

    def make_wheel(
        self,
        root: Path,
        *,
        extra_entry: str | None = None,
        metadata: str | None = None,
        include_metadata: bool = True,
        extra_dist_info: bool = False,
        symlink: bool = False,
        extra_content: str = "fixture",
        metadata_mode: int | None = None,
        wheel_headers: str = "Wheel-Version: 1.0\nTag: py3-none-any\n",
    ) -> Path:
        wheel = root / "local_gpu_imagegen-0.8.0-py3-none-any.whl"
        metadata = metadata or (
            "Metadata-Version: 2.4\nName: local-gpu-imagegen\nVersion: 0.8.0\n"
            "Requires-Python: >=3.11\n\n"
        )
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("local_gpu_imagegen/__init__.py", '__version__ = "0.8.0"\n')
            if include_metadata:
                if metadata_mode is None:
                    archive.writestr("local_gpu_imagegen-0.8.0.dist-info/METADATA", metadata)
                else:
                    info = zipfile.ZipInfo("local_gpu_imagegen-0.8.0.dist-info/METADATA")
                    info.external_attr = metadata_mode << 16
                    archive.writestr(info, metadata)
            archive.writestr(
                "local_gpu_imagegen-0.8.0.dist-info/WHEEL",
                wheel_headers,
            )
            archive.writestr("local_gpu_imagegen-0.8.0.dist-info/RECORD", "")
            if extra_dist_info:
                archive.writestr("other-1.0.dist-info/METADATA", metadata)
            if extra_entry is not None:
                if symlink:
                    info = zipfile.ZipInfo(extra_entry)
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, "target")
                elif "\\" in extra_entry:
                    info = zipfile.ZipInfo("placeholder")
                    info.filename = extra_entry
                    info.orig_filename = extra_entry
                    archive.writestr(info, extra_content)
                else:
                    archive.writestr(extra_entry, extra_content)
        return wheel

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_wheel_binds_hash_metadata_and_registry_descriptor(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        results, facts = checks.inspect_wheel(root, wheel, digest)
        self.assertEqual(self.blocked_ids(results), set())
        self.assertEqual(facts["version"], "0.8.0")
        self.assertEqual(facts["registry_identifier"], "local-gpu-imagegen")

    def test_wheel_returns_sorted_unique_checks_with_explicit_dist_info(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assert_result_contract(results)
        by_id = {str(item["id"]): item for item in results}
        self.assertEqual(by_id["wheel_dist_info"]["status"], "passed")

        with patch.object(checks, "_archive_bytes", side_effect=RuntimeError("late read failure")):
            failed, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assert_result_contract(failed)
        archive_checks = [item for item in failed if item["id"] == "wheel_archive"]
        self.assertEqual(archive_checks, [checks.blocked_check("wheel_archive", "wheel_archive_invalid")])

    def test_wheel_rejects_traversal_link_weights_and_private_entries(self) -> None:
        for entry in (
            "../escape.py",
            "C:/absolute.py",
            "models/private.safetensors",
            "outputs/runs/private.json",
        ):
            with self.subTest(entry=entry):
                root = self.make_release_root()
                wheel = self.make_wheel(root, extra_entry=entry)
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("unsafe_wheel_entry", self.codes(results))

    def test_wheel_rejects_case_insensitive_private_directories(self) -> None:
        for entry in ("Models/private.safetensors", "package/OUTPUTS/run.json"):
            with self.subTest(entry=entry):
                root = self.make_release_root()
                wheel = self.make_wheel(root, extra_entry=entry)
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("unsafe_wheel_entry", self.codes(results))

    def test_wheel_rejects_filename_hash_and_dist_info_failures(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        wrong_name = root / "wrong.whl"
        wheel.rename(wrong_name)
        results, _ = checks.inspect_wheel(root, wrong_name, self.sha(wrong_name))
        self.assertIn("wheel_filename_mismatch", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(root, include_metadata=False)
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_dist_info_invalid", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(root, extra_dist_info=True)
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_dist_info_invalid", self.codes(results))

        results, _ = checks.inspect_wheel(root, wheel, "f" * 64)
        self.assertIn("wheel_sha256_mismatch", self.codes(results))
        results, _ = checks.inspect_wheel(root, wheel, "F" * 64)
        self.assertIn("candidate_sha256_invalid", self.codes(results))

    def test_wheel_rejects_metadata_and_descriptor_drift(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(
            root,
            metadata="Metadata-Version: 2.4\nName: local-gpu-imagegen\nVersion: 0.8.0\n"
            "Requires-Python: >=3.12\nRequires-Dist: requests\n\n",
        )
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_metadata_invalid", self.codes(results))

        (root / "pyproject.toml").write_text("[project]\nname = 'drift'\n", encoding="utf-8")
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("project_metadata_drift", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(root)
        (root / "server.json").write_text('{"packages": []}', encoding="utf-8")
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("registry_descriptor_drift", self.codes(results))

    def test_wheel_rejects_duplicate_or_conflicting_metadata_identity_headers(self) -> None:
        identity_headers = {
            "Name": ("local-gpu-imagegen", "other-project"),
            "Version": ("0.8.0", "9.9.9"),
            "Requires-Python": (">=3.11", ">=3.12"),
        }
        base = (
            "Metadata-Version: 2.4\nName: local-gpu-imagegen\nVersion: 0.8.0\n"
            "Requires-Python: >=3.11\n"
        )
        for header, (expected, conflicting) in identity_headers.items():
            for duplicate in (expected, conflicting):
                with self.subTest(header=header, duplicate=duplicate):
                    root = self.make_release_root()
                    wheel = self.make_wheel(
                        root,
                        metadata=f"{base}{header}: {duplicate}\n\n",
                    )
                    results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                    self.assertIn("wheel_metadata_invalid", self.codes(results))

    def test_wheel_rejects_unsafe_zip_forms_and_sensitive_content(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root, extra_entry="local_gpu_imagegen\\bad.py")
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("unsafe_wheel_entry", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(root, extra_entry="local_gpu_imagegen/link", symlink=True)
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("unsafe_wheel_entry", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(
            root,
            extra_entry="local_gpu_imagegen/private_path.py",
            extra_content="C:\\Users\\private",
        )
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("sensitive_wheel_content", self.codes(results))

    def test_wheel_cross_validates_directory_paths_and_unix_file_types(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        with zipfile.ZipFile(wheel, "a") as archive:
            directory = zipfile.ZipInfo("local_gpu_imagegen/directory/")
            directory.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(directory, "")
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("unsafe_wheel_entry", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(root, metadata_mode=stat.S_IFDIR | 0o755)
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("unsafe_wheel_entry", self.codes(results))

    def test_wheel_rejects_ambiguous_member_names_and_nonempty_directories(self) -> None:
        root = self.make_release_root()
        source_name = b"local_gpu_imagegen/nul.pyXignored"
        nul_name = b"local_gpu_imagegen/nul.py\0ignored"
        wheel = self.make_wheel(root, extra_entry=source_name.decode("ascii"))
        wheel_bytes = wheel.read_bytes()
        self.assertEqual(wheel_bytes.count(source_name), 2)
        wheel.write_bytes(wheel_bytes.replace(source_name, nul_name))
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("unsafe_wheel_entry", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(
            root,
            extra_entry="local_gpu_imagegen/nonempty/",
            extra_content="payload",
        )
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("unsafe_wheel_entry", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(root, extra_entry="LOCAL_GPU_IMAGEGEN/__init__.py")
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("unsafe_wheel_entry", self.codes(results))

    def test_wheel_rejects_parser_defects_in_metadata_and_wheel_headers(self) -> None:
        malformed_metadata = (
            "Metadata-Version: 2.4\nName: local-gpu-imagegen\nVersion: 0.8.0\n"
            "Requires-Python: >=3.11\nBad Header: value\n\n"
        )
        malformed_wheel = "Wheel-Version: 1.0\nTag: py3-none-any\nBad Header: value\n\n"
        for wheel_args in (
            {"metadata": malformed_metadata},
            {"wheel_headers": malformed_wheel},
        ):
            with self.subTest(wheel_args=wheel_args):
                root = self.make_release_root()
                wheel = self.make_wheel(root, **wheel_args)
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("wheel_metadata_invalid", self.codes(results))

    def test_registry_descriptor_rejects_duplicate_keys_at_every_object_level(self) -> None:
        replacements = (
            ('"version": "0.8.0",', '"version": "0.8.0",\n  "version": "0.8.0",'),
            ('"runtimeHint": "uvx",', '"runtimeHint": "uvx",\n      "runtimeHint": "uvx",'),
            ('"type": "stdio"', '"type": "stdio",\n        "type": "stdio"'),
        )
        for old, duplicate in replacements:
            with self.subTest(key=old):
                root = self.make_release_root()
                descriptor = (root / "server.json").read_text(encoding="utf-8")
                (root / "server.json").write_text(
                    descriptor.replace(old, duplicate, 1),
                    encoding="utf-8",
                )
                wheel = self.make_wheel(root)
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("registry_descriptor_drift", self.codes(results))

    def test_wheel_rejects_broader_private_paths_and_credential_markers(self) -> None:
        sensitive_values = (
            "D:\\Users\\private\\model.safetensors",
            "E:/Users/private/model.safetensors",
            "/Users/private/model.safetensors",
            "X-API-Key: secret-value",
            "client_secret = secret-value",
            "Password: secret-value",
        )
        for content in sensitive_values:
            with self.subTest(content=content):
                root = self.make_release_root()
                wheel = self.make_wheel(
                    root,
                    extra_entry="local_gpu_imagegen/private.txt",
                    extra_content=content,
                )
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("sensitive_wheel_content", self.codes(results))

    def test_wheel_rejects_quoted_credential_keys_without_leaking_content(self) -> None:
        for content in (
            '{"client_secret":"value"}',
            '{"password":"value"}',
            '{"token":"value"}',
        ):
            with self.subTest(content=content):
                root = self.make_release_root()
                wheel = self.make_wheel(
                    root,
                    extra_entry="local_gpu_imagegen/private.txt",
                    extra_content=content,
                )
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("sensitive_wheel_content", self.codes(results))
                self.assertNotIn(content, str(results))

    def test_wheel_rejects_generic_windows_absolute_paths(self) -> None:
        for content in (
            "D:\\AI\\models\\private.safetensors",
            "E:\\models\\private.safetensors",
        ):
            with self.subTest(content=content):
                root = self.make_release_root()
                wheel = self.make_wheel(
                    root,
                    extra_entry="local_gpu_imagegen/private.txt",
                    extra_content=content,
                )
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("sensitive_wheel_content", self.codes(results))

    def test_wheel_hash_and_zip_parse_the_same_single_opened_snapshot(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        digest = self.sha(wheel)
        original_open = Path.open
        wheel_open_count = 0

        class ReplacePathOnClose:
            def __init__(self, source: object) -> None:
                self.source = source

            def __enter__(self) -> object:
                return self

            def __exit__(self, *args: object) -> None:
                self.source.close()  # type: ignore[attr-defined]
                with original_open(wheel, "wb") as replacement:
                    replacement.write(b"replacement is not a zip")

            def __getattr__(self, name: str) -> object:
                return getattr(self.source, name)

        def tracked_open(path: Path, *args: object, **kwargs: object) -> object:
            nonlocal wheel_open_count
            opened = original_open(path, *args, **kwargs)
            if path == wheel and (not args or args[0] == "rb"):
                wheel_open_count += 1
                return ReplacePathOnClose(opened)
            return opened

        with (
            patch.object(Path, "open", tracked_open),
            patch.object(checks.zipfile, "ZipFile", wraps=zipfile.ZipFile) as zip_file,
        ):
            results, facts = checks.inspect_wheel(root, wheel, digest)

        self.assertEqual(self.blocked_ids(results), set())
        self.assertEqual(facts["sha256"], digest)
        self.assertEqual(wheel_open_count, 1)
        self.assertNotEqual(zip_file.call_args.args[0], wheel)

    def test_wheel_rejects_opened_nonregular_reparse_or_changed_objects(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        digest = self.sha(wheel)
        real_stat = os.stat(wheel)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

        cases = (
            (stat.S_IFDIR, 0, real_stat.st_size, "wheel_not_regular"),
            (stat.S_IFREG, reparse_flag, real_stat.st_size, "wheel_not_regular"),
        )
        for mode, attributes, size, expected_code in cases:
            with self.subTest(expected_code=expected_code, attributes=attributes):
                opened_stat = type(
                    "OpenedStat",
                    (),
                    {
                        "st_mode": mode,
                        "st_file_attributes": attributes,
                        "st_size": size,
                        "st_dev": real_stat.st_dev,
                        "st_ino": real_stat.st_ino,
                    },
                )()
                with patch.object(checks.os, "fstat", return_value=opened_stat):
                    results, _ = checks.inspect_wheel(root, wheel, digest)
                self.assertIn(expected_code, self.codes(results))

        initial_stat = type(
            "OpenedStat",
            (),
            {
                "st_mode": stat.S_IFREG,
                "st_file_attributes": 0,
                "st_size": real_stat.st_size,
                "st_dev": real_stat.st_dev,
                "st_ino": real_stat.st_ino,
            },
        )()
        for final_size in (real_stat.st_size - 1, real_stat.st_size + 1):
            with self.subTest(final_size=final_size):
                changed_stat = type(
                    "OpenedStat",
                    (),
                    {
                        "st_mode": stat.S_IFREG,
                        "st_file_attributes": 0,
                        "st_size": final_size,
                        "st_dev": real_stat.st_dev,
                        "st_ino": real_stat.st_ino,
                    },
                )()
                with patch.object(checks.os, "fstat", side_effect=(initial_stat, changed_stat)):
                    results, _ = checks.inspect_wheel(root, wheel, digest)
                self.assertIn("wheel_changed_during_read", self.codes(results))

    def test_wheel_rejects_lstat_path_types_before_open(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        digest = self.sha(wheel)
        real_stat = os.lstat(wheel)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        original_open = Path.open

        for mode, attributes in (
            (stat.S_IFDIR, 0),
            (stat.S_IFREG, reparse_flag),
        ):
            with self.subTest(mode=mode, attributes=attributes):
                path_stat = type(
                    "PathStat",
                    (),
                    {
                        "st_mode": mode,
                        "st_file_attributes": attributes,
                        "st_size": real_stat.st_size,
                        "st_dev": real_stat.st_dev,
                        "st_ino": real_stat.st_ino,
                    },
                )()
                opened_paths: list[Path] = []

                def tracked_open(path: Path, *args: object, **kwargs: object) -> object:
                    opened_paths.append(path)
                    return original_open(path, *args, **kwargs)

                with (
                    patch.object(checks.os, "lstat", return_value=path_stat),
                    patch.object(Path, "open", tracked_open),
                    patch.object(checks.zipfile, "ZipFile", wraps=zipfile.ZipFile) as zip_file,
                ):
                    results, _ = checks.inspect_wheel(root, wheel, digest)

                self.assertIn("wheel_not_regular", self.codes(results))
                self.assertEqual(opened_paths, [])
                zip_file.assert_not_called()

    def test_wheel_rejects_identity_change_between_lstat_and_open(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        digest = self.sha(wheel)
        path_stat = os.lstat(wheel)
        original_open = Path.open
        opened_paths: list[Path] = []
        replaced_stat = type(
            "OpenedStat",
            (),
            {
                "st_mode": stat.S_IFREG,
                "st_file_attributes": 0,
                "st_size": path_stat.st_size,
                "st_dev": path_stat.st_dev,
                "st_ino": path_stat.st_ino + 1,
            },
        )()

        def tracked_open(path: Path, *args: object, **kwargs: object) -> object:
            opened_paths.append(path)
            return original_open(path, *args, **kwargs)

        with (
            patch.object(checks.os, "fstat", return_value=replaced_stat),
            patch.object(Path, "open", tracked_open),
            patch.object(checks.zipfile, "ZipFile", wraps=zipfile.ZipFile) as zip_file,
        ):
            results, _ = checks.inspect_wheel(root, wheel, digest)

        self.assertIn("wheel_identity_changed", self.codes(results))
        self.assertEqual(opened_paths, [wheel])
        zip_file.assert_not_called()

    def test_wheel_rejects_a_stream_read_over_the_outer_budget(self) -> None:
        root = self.make_release_root()
        wheel = root / checks.EXPECTED_WHEEL
        with wheel.open("wb") as target:
            target.truncate(checks.MAX_WHEEL_BYTES + 1)
        real_stat = os.lstat(wheel)
        reported_stat = type(
            "OpenedStat",
            (),
            {
                "st_mode": stat.S_IFREG,
                "st_file_attributes": 0,
                "st_size": checks.MAX_WHEEL_BYTES,
                "st_dev": real_stat.st_dev,
                "st_ino": real_stat.st_ino,
            },
        )()

        with (
            patch.object(checks.os, "lstat", return_value=reported_stat),
            patch.object(checks.os, "fstat", return_value=reported_stat),
            patch.object(checks.zipfile, "ZipFile") as zip_file,
        ):
            results, _ = checks.inspect_wheel(root, wheel, "0" * 64)

        self.assertIn("wheel_file_too_large", self.codes(results))
        zip_file.assert_not_called()

    def test_wheel_rejects_archive_size_limits(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        with zipfile.ZipFile(wheel, "a") as archive:
            for number in range(257):
                archive.writestr(f"local_gpu_imagegen/extra-{number}.py", "x")
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_archive_too_large", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(root)
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("local_gpu_imagegen/large.py", b"x" * (2 * 1024 * 1024 + 1))
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_archive_too_large", self.codes(results))

    def test_wheel_rejects_oversized_file_before_hash_or_zip_open(self) -> None:
        root = self.make_release_root()
        wheel = root / checks.EXPECTED_WHEEL
        with wheel.open("wb") as target:
            target.truncate(checks.MAX_WHEEL_BYTES + 1)

        with (
            patch.object(checks.zipfile, "ZipFile") as zip_file,
        ):
            results, _ = checks.inspect_wheel(root, wheel, "0" * 64)

        self.assertIn("wheel_file_too_large", self.codes(results))
        zip_file.assert_not_called()

    def test_wheel_rejects_total_size_overflow_without_reading_entries(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        with zipfile.ZipFile(wheel, "a") as archive:
            for number in range(9):
                archive.writestr(f"local_gpu_imagegen/{number}.bin", b"x" * 1_900_000)
        with patch.object(checks, "_archive_bytes", wraps=checks._archive_bytes) as archive_bytes:
            results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_archive_too_large", self.codes(results))
        archive_bytes.assert_not_called()

    def test_wheel_rejects_duplicate_members_and_malformed_wheel_headers(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        with zipfile.ZipFile(wheel, "a") as archive:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(
                    "local_gpu_imagegen-0.8.0.dist-info/METADATA",
                    "Metadata-Version: 2.4\nName: local-gpu-imagegen\nVersion: 0.8.0\n"
                    "Requires-Python: >=3.11\n\n",
                )
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_dist_info_invalid", self.codes(results))

        root = self.make_release_root()
        wheel = self.make_wheel(
            root,
            wheel_headers="Wheel-Version: 1.0\nTag: py3-none-any-extra\n",
        )
        results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_metadata_invalid", self.codes(results))

        for wheel_version in (
            "Wheel-Version: 1.0\nWheel-Version: 1.0\n",
            "Wheel-Version: 1.0\nWheel-Version: 2.0\n",
        ):
            with self.subTest(wheel_version=wheel_version):
                root = self.make_release_root()
                wheel = self.make_wheel(root, wheel_headers=wheel_version + "Tag: py3-none-any\n")
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("wheel_metadata_invalid", self.codes(results))

    def test_wheel_rejects_non_normalized_member_spelling(self) -> None:
        for entry in ("local_gpu_imagegen//file.py", "local_gpu_imagegen/./file.py"):
            with self.subTest(entry=entry):
                root = self.make_release_root()
                wheel = self.make_wheel(root, extra_entry=entry)
                results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn("unsafe_wheel_entry", self.codes(results))

    def test_wheel_does_not_read_content_after_unsafe_or_invalid_layout(self) -> None:
        cases = (
            ({"extra_entry": "../escape.py"}, "unsafe_wheel_entry"),
            ({"include_metadata": False}, "wheel_dist_info_invalid"),
        )
        for wheel_args, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                root = self.make_release_root()
                wheel = self.make_wheel(root, **wheel_args)
                with patch.object(checks, "_archive_bytes", wraps=checks._archive_bytes) as archive_bytes:
                    results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
                self.assertIn(expected_code, self.codes(results))
                archive_bytes.assert_not_called()

    def test_wheel_reports_hash_read_failure_without_exception(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        digest = self.sha(wheel)
        with patch.object(Path, "open", side_effect=OSError("unavailable")):
            results, _ = checks.inspect_wheel(root, wheel, digest)
        self.assertEqual(self.codes(results), {"wheel_unavailable"})

    def test_wheel_reports_archive_read_failure_without_error_text(self) -> None:
        root = self.make_release_root()
        wheel = self.make_wheel(root)
        with patch.object(checks, "_archive_bytes", side_effect=RuntimeError("encrypted member")):
            results, _ = checks.inspect_wheel(root, wheel, self.sha(wheel))
        self.assertIn("wheel_archive_invalid", self.codes(results))
        self.assertNotIn("encrypted member", str(results))


class RecordingRunner:
    def __init__(self, responses: list[subprocess.CompletedProcess[str]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(
        self, command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(kwargs)))
        if not self.responses:
            raise AssertionError(f"unexpected subprocess: {command}")
        return self.responses.pop(0)


class ReleaseCandidateInstalledTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp = Path(self.temporary_directory.name)
        self.wheel = self.temp / checks.EXPECTED_WHEEL
        self.wheel.write_bytes(b"wheel fixture")
        self.python = self.temp / "python312"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def codes(results: list[dict[str, object]]) -> set[str]:
        return {str(item["code"]) for item in results if item["status"] == "blocked"}

    def valid_responses(self) -> dict[str, object]:
        return {
            "version": [3, 12],
            "verify": {
                "ok": True,
                "server": {"version": "0.8.0"},
                "protocolVersion": "2024-11-05",
                "tools": list(checks.EXPECTED_TOOLS),
            },
            "doctor": {"ready": False},
            "codex": {"status": "planned", "applied": False},
            "claude": {"status": "planned", "applied": False},
            "compile": {"compiled_sources": 7, "ok": True},
        }

    def completed_processes(self, responses: dict[str, object]) -> list[subprocess.CompletedProcess[str]]:
        return [
            subprocess.CompletedProcess(["python"], 0, json.dumps(responses["version"]), ""),
            subprocess.CompletedProcess(["venv"], 0, "", ""),
            subprocess.CompletedProcess(["venv-python"], 0, json.dumps(responses["version"]), ""),
            subprocess.CompletedProcess(["pip"], 0, "", ""),
            subprocess.CompletedProcess(["verify"], 0, json.dumps(responses["verify"]), ""),
            subprocess.CompletedProcess(["doctor"], 1, json.dumps(responses["doctor"]), ""),
            subprocess.CompletedProcess(["setup", "codex"], 0, json.dumps(responses["codex"]), ""),
            subprocess.CompletedProcess(["setup", "claude"], 0, json.dumps(responses["claude"]), ""),
            subprocess.CompletedProcess(["compileall"], 0, json.dumps(responses["compile"]), ""),
        ]

    def valid_completed_processes(self) -> list[subprocess.CompletedProcess[str]]:
        return self.completed_processes(self.valid_responses())

    def run_with(self, runner: RecordingRunner) -> tuple[list[dict[str, object]], dict[str, object]]:
        return checks.run_installed_checks(self.wheel, self.python, runner=runner)

    def test_valid_path_uses_supplied_python_to_create_and_verify_venv(self) -> None:
        runner = RecordingRunner(self.valid_completed_processes())
        results, facts = self.run_with(runner)

        self.assertFalse(self.codes(results), results)
        ids = [str(item["id"]) for item in results]
        self.assertEqual(
            ids,
            [
                "installed_compile",
                "installed_contract",
                "installed_doctor",
                "installed_pip",
                "installed_protocol",
                "installed_setup_claude",
                "installed_setup_codex",
                "installed_tools",
                "installed_venv",
                "installed_venv_python",
                "installed_version",
                "release_python",
            ],
        )
        self.assertEqual(
            facts,
            {
                "release_python_version": [3, 12],
                "venv_python_version": [3, 12],
                "version": "0.8.0",
                "protocol": "2024-11-05",
                "tool_count": 17,
                "tools": list(checks.EXPECTED_TOOLS),
                "doctor_exit": 1,
                "doctor_ready": False,
                "codex_dry_run": "planned",
                "claude_dry_run": "planned",
                "compiled_source_count": 7,
            },
        )

        version, create, venv_version, install = runner.calls[:4]
        temporary_root = Path(str(create[0][3])).parent
        self.assertEqual(
            version[0],
            [str(self.python), "-c", checks.PYTHON_VERSION_SCRIPT],
        )
        self.assertEqual(
            create[0],
            [
                str(self.python),
                "-c",
                checks.CREATE_VENV_SCRIPT,
                str(temporary_root / "venv"),
            ],
        )
        installed_python = temporary_root / "venv" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        self.assertEqual(
            venv_version[0],
            [str(installed_python), "-c", checks.PYTHON_VERSION_SCRIPT],
        )
        self.assertEqual(
            install[0],
            [
                str(installed_python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--no-cache-dir",
                "--disable-pip-version-check",
                str(self.wheel.resolve()),
            ],
        )
        for _, kwargs in runner.calls:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            for name in ("PYTHONPATH", "PYTHONHOME", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"):
                self.assertNotIn(name, environment)
            self.assertEqual(environment["PIP_NO_INDEX"], "1")
            self.assertEqual(environment["PIP_DISABLE_PIP_VERSION_CHECK"], "1")
            self.assertEqual(environment["LOCAL_GPU_IMAGEGEN_WEBUI_URL"], "http://127.0.0.1:1")
            self.assertEqual(environment["LOCAL_GPU_IMAGEGEN_COMFYUI_URL"], "http://127.0.0.1:1")
            self.assertTrue(str(environment["PATH"]).startswith(str(temporary_root / "fake-bin")))
            self.assertEqual(kwargs["cwd"], temporary_root)
            self.assertNotEqual(Path(str(kwargs["cwd"])), ROOT)
            self.assertEqual(kwargs["timeout"], 60)
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            self.assertFalse(kwargs["check"])

    def test_environment_scrubs_hostile_proxy_variables_and_forces_no_proxy(self) -> None:
        hostile = {
            "HTTP_PROXY": "http://proxy.invalid:8080",
            "https_proxy": "http://proxy.invalid:8080",
            "All_PrOxY": "socks5://proxy.invalid:1080",
            "NO_PROXY": "localhost",
            "no_proxy": "127.0.0.1",
        }
        with patch.dict(checks.os.environ, hostile, clear=False):
            runner = RecordingRunner(self.valid_completed_processes())
            self.run_with(runner)

        for _, kwargs in runner.calls:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            proxy_names = {
                name for name in environment if name.casefold().endswith("_proxy")
            }
            self.assertEqual(proxy_names, {"NO_PROXY", "no_proxy"})
            self.assertEqual(environment["NO_PROXY"], "*")
            self.assertEqual(environment["no_proxy"], "*")

    def test_checkout_child_temporary_root_fails_before_any_work(self) -> None:
        temporary_root = ROOT / f"task-2-temp-{uuid.uuid4().hex}"
        temporary_root.mkdir()

        class CheckoutTemporaryDirectory:
            def __enter__(self) -> str:
                return str(temporary_root)

            def __exit__(self, *args: object) -> None:
                return None

        runner = RecordingRunner([])
        try:
            with patch.object(checks.tempfile, "TemporaryDirectory", CheckoutTemporaryDirectory):
                results, facts = self.run_with(runner)
        finally:
            shutil.rmtree(temporary_root)

        self.assertEqual(self.codes(results), {"installed_checkout_external_required"})
        self.assertEqual(facts, {})
        self.assertEqual(runner.calls, [])

    def test_compile_rejects_boolean_source_count(self) -> None:
        responses = self.valid_responses()
        compile_result = responses["compile"]
        assert isinstance(compile_result, dict)
        compile_result["compiled_sources"] = True

        results, _ = self.run_with(RecordingRunner(self.completed_processes(responses)))

        self.assertIn("installed_compile_failed", self.codes(results))

    def test_installed_contract_requires_exact_version_protocol_and_tools(self) -> None:
        cases = (
            ("version", "installed_version_mismatch", "0.8.1"),
            ("protocol", "installed_protocol_mismatch", "2025-01-01"),
            ("tools", "installed_tool_contract_mismatch", list(reversed(checks.EXPECTED_TOOLS))),
        )
        for field, expected, value in cases:
            with self.subTest(field=field):
                responses = self.valid_responses()
                verify = responses["verify"]
                assert isinstance(verify, dict)
                if field == "version":
                    server = verify["server"]
                    assert isinstance(server, dict)
                    server["version"] = value
                elif field == "protocol":
                    verify["protocolVersion"] = value
                else:
                    verify["tools"] = value
                results, _ = self.run_with(RecordingRunner(self.completed_processes(responses)))
                self.assertIn(expected, self.codes(results))

    def test_failures_are_mapped_without_tracebacks(self) -> None:
        cases = (
            ("pip", 1, "installed_pip_install_failed"),
            ("verify", 0, "installed_json_invalid"),
            ("doctor", 0, "installed_doctor_mismatch"),
            ("setup", 0, "installed_setup_contract_mismatch"),
            ("compile", 1, "installed_compile_failed"),
        )
        for target, returncode, expected in cases:
            with self.subTest(target=target):
                responses = self.valid_responses()
                if target == "verify":
                    completed = self.completed_processes(responses)
                    completed[4] = subprocess.CompletedProcess(["verify"], returncode, "not-json", "")
                elif target == "pip":
                    completed = self.completed_processes(responses)
                    completed[3] = subprocess.CompletedProcess(["pip"], returncode, "", "Traceback: private")
                elif target == "doctor":
                    completed = self.completed_processes(responses)
                    completed[5] = subprocess.CompletedProcess(["doctor"], returncode, json.dumps(responses["doctor"]), "")
                elif target == "setup":
                    completed = self.completed_processes(responses)
                    completed[6] = subprocess.CompletedProcess(
                        ["setup", "codex"], returncode,
                        json.dumps({"status": "configured", "applied": True}), "",
                    )
                else:
                    completed = self.completed_processes(responses)
                    completed[8] = subprocess.CompletedProcess(["compileall"], returncode, "", "")
                results, _ = self.run_with(RecordingRunner(completed))
                self.assertIn(expected, self.codes(results))
                self.assertNotIn("private", str(results))

    def test_json_boundary_rejects_empty_oversized_non_object_traceback_and_timeout(self) -> None:
        cases: list[object] = ["", "x" * (1024 * 1024 + 1), "[]", '{"ok": true}']
        for output in cases:
            with self.subTest(output_type=type(output).__name__, size=len(output)):
                completed = self.valid_completed_processes()
                stderr = "Traceback: private" if output == '{"ok": true}' else ""
                completed[4] = subprocess.CompletedProcess(["verify"], 0, output, stderr)
                results, _ = self.run_with(RecordingRunner(completed))
                self.assertIn("installed_json_invalid", self.codes(results))
                self.assertNotIn("private", str(results))

        recording = RecordingRunner(self.valid_completed_processes())

        def timeout_on_verify(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            completed = recording(command, **kwargs)
            if command[-1:] == ["verify"]:
                raise subprocess.TimeoutExpired(command, 60)
            return completed

        results, _ = self.run_with(timeout_on_verify)  # type: ignore[arg-type]
        self.assertIn("installed_contract_mismatch", self.codes(results))

    def test_doctor_ready_true_is_blocked(self) -> None:
        completed = self.valid_completed_processes()
        completed[5] = subprocess.CompletedProcess(["doctor"], 1, '{"ready": true}', "")
        results, _ = self.run_with(RecordingRunner(completed))
        self.assertIn("installed_doctor_mismatch", self.codes(results))

    def test_setup_marker_creation_is_blocked(self) -> None:
        recording = RecordingRunner(self.valid_completed_processes())

        def marking_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            completed = recording(command, **kwargs)
            if command[-2:] == ["setup", "codex"]:
                Path(str(kwargs["cwd"]), "fake-bin", "client-add-called").write_text("called")
            return completed

        results, _ = self.run_with(marking_runner)  # type: ignore[arg-type]
        self.assertIn("installed_setup_contract_mismatch", self.codes(results))

    def test_python_gate_rejects_wrong_malformed_missing_and_timeout_before_venv(self) -> None:
        cases: list[object] = ["[3, 11]", "not-json", OSError("missing"), subprocess.TimeoutExpired(["python"], 60)]
        for response in cases:
            with self.subTest(response=type(response).__name__):
                runner = RecordingRunner([])
                if isinstance(response, str):
                    runner.responses.append(subprocess.CompletedProcess(["python"], 0, response, ""))
                else:
                    def failing_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                        raise response
                    runner = failing_runner  # type: ignore[assignment]
                results, _ = checks.run_installed_checks(self.wheel, self.python, runner=runner)
                self.assertIn("release_python_312_required", self.codes(results))

    def test_created_venv_must_report_python_312_before_install(self) -> None:
        completed = self.valid_completed_processes()
        completed[2] = subprocess.CompletedProcess(["venv-python"], 0, "[3, 13]", "")
        runner = RecordingRunner(completed)
        results, _ = self.run_with(runner)
        self.assertIn("release_python_312_required", self.codes(results))
        self.assertEqual(len(runner.calls), 3)

    def test_cleanup_after_runner_exception_and_setup_marker_creation(self) -> None:
        created: list[Path] = []
        original = tempfile.TemporaryDirectory

        class CapturingTemporaryDirectory:
            def __init__(self) -> None:
                self.delegate = original()
                self.name = self.delegate.name
                created.append(Path(self.name))

            def __enter__(self) -> str:
                return self.name

            def __exit__(self, *args: object) -> None:
                self.delegate.cleanup()

        def exploding_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[1:2] == ["-c"] and command[0] == str(self.python):
                return subprocess.CompletedProcess(command, 0, "[3, 12]", "")
            raise subprocess.TimeoutExpired(command, 60)

        with patch.object(checks.tempfile, "TemporaryDirectory", CapturingTemporaryDirectory):
            results, _ = checks.run_installed_checks(self.wheel, self.python, runner=exploding_runner)
        self.assertIn("release_python_312_required", self.codes(results))
        self.assertTrue(created)
        self.assertFalse(created[0].exists())
