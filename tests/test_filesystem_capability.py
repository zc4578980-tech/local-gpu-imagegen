from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_gpu_imagegen import _filesystem_capability  # noqa: E402
from local_gpu_imagegen._filesystem_capability import (  # noqa: E402
    open_exclusive_output,
    remove_owned_path,
)


class FilesystemCapabilityTests(unittest.TestCase):
    def test_final_handle_path_mismatch_fails_before_nonempty_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            destination = root / "owned.tmp"
            root_identity = root.lstat()
            original_final_path = _filesystem_capability._final_path_for_descriptor
            calls = 0

            def redirect_opened_file(descriptor: int) -> str:
                nonlocal calls
                calls += 1
                if calls == 2:
                    return str(root / "external" / destination.name)
                return original_final_path(descriptor)

            with mock.patch.object(
                _filesystem_capability,
                "_final_path_for_descriptor",
                side_effect=redirect_opened_file,
            ), self.assertRaises(OSError):
                open_exclusive_output(destination, root_identity)

            self.assertTrue(not destination.exists() or destination.read_bytes() == b"")

    def test_capability_cleanup_deletes_exact_owned_file_and_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            owned_file = root / "owned.tmp"
            owned_file.write_bytes(b"owned")
            file_identity = owned_file.lstat()
            owned_directory = root / "owned-dir"
            owned_directory.mkdir()
            directory_identity = owned_directory.lstat()

            self.assertTrue(remove_owned_path(owned_file, file_identity, directory=False))
            self.assertTrue(remove_owned_path(owned_directory, directory_identity, directory=True))
            self.assertFalse(os.path.lexists(owned_file))
            self.assertFalse(os.path.lexists(owned_directory))

    def test_unavailable_capability_cleanup_retains_owned_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            owned_file = Path(temporary_directory) / "owned.tmp"
            owned_file.write_bytes(b"owned")
            identity = owned_file.lstat()

            with mock.patch.object(
                _filesystem_capability,
                "_delete_open_descriptor",
                return_value=False,
            ):
                removed = remove_owned_path(owned_file, identity, directory=False)

            self.assertFalse(removed)
            self.assertEqual(owned_file.read_bytes(), b"owned")

    def test_cleanup_rejects_a_replacement_opened_for_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            owned_file = root / "owned.tmp"
            owned_file.write_bytes(b"owned")
            identity = owned_file.lstat()
            displaced = root / "displaced.tmp"
            replacement = root / "replacement.tmp"
            replacement.write_bytes(b"replacement")
            original_open = _filesystem_capability._open_delete_descriptor

            def replace_before_delete(path: Path, *, directory: bool) -> int:
                owned_file.replace(displaced)
                replacement.replace(owned_file)
                return original_open(path, directory=directory)

            with mock.patch.object(
                _filesystem_capability,
                "_open_delete_descriptor",
                side_effect=replace_before_delete,
            ):
                removed = remove_owned_path(owned_file, identity, directory=False)

            self.assertFalse(removed)
            self.assertEqual(owned_file.read_bytes(), b"replacement")
            self.assertEqual(displaced.read_bytes(), b"owned")

    @unittest.skipUnless(os.name == "nt", "Windows handle-bound disposition semantics")
    def test_cleanup_remains_bound_when_path_is_replaced_after_handle_open(self) -> None:
        for directory in (False, True):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                owned = root / "owned"
                replacement = root / "replacement"
                if directory:
                    owned.mkdir()
                    replacement.mkdir()
                else:
                    owned.write_bytes(b"owned")
                    replacement.write_bytes(b"replacement")
                identity = owned.lstat()
                displaced = root / "displaced"
                original_delete = _filesystem_capability._delete_open_descriptor

                def replace_after_open(capability) -> bool:
                    owned.replace(displaced)
                    replacement.replace(owned)
                    return original_delete(capability)

                with mock.patch.object(
                    _filesystem_capability,
                    "_delete_open_descriptor",
                    side_effect=replace_after_open,
                ):
                    removed = remove_owned_path(owned, identity, directory=directory)

                self.assertTrue(removed)
                self.assertTrue(owned.is_dir() if directory else owned.is_file())
                self.assertFalse(os.path.lexists(displaced))
                if not directory:
                    self.assertEqual(owned.read_bytes(), b"replacement")


if __name__ == "__main__":
    unittest.main()
