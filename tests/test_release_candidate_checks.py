from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path


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

        shutil.rmtree(self.temp, onexc=remove_readonly)

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
        self.assertEqual(len(facts["untracked_files"]), 20)

        def unavailable(_: Path, *args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 1, "", "not a repository")

        results, _ = checks.inspect_checkout(root, commit, runner=unavailable)
        self.assertIn("git_checkout_unavailable", self.codes(results))


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
    ) -> Path:
        wheel = root / "local_gpu_imagegen-0.8.0-py3-none-any.whl"
        metadata = metadata or (
            "Metadata-Version: 2.4\nName: local-gpu-imagegen\nVersion: 0.8.0\n"
            "Requires-Python: >=3.11\n\n"
        )
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("local_gpu_imagegen/__init__.py", '__version__ = "0.8.0"\n')
            if include_metadata:
                archive.writestr("local_gpu_imagegen-0.8.0.dist-info/METADATA", metadata)
            archive.writestr(
                "local_gpu_imagegen-0.8.0.dist-info/WHEEL",
                "Wheel-Version: 1.0\nTag: py3-none-any\n",
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
