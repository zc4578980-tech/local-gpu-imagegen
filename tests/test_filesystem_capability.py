from __future__ import annotations

import errno
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
    promote_owned_path_no_replace,
    remove_owned_path,
)


class FilesystemCapabilityTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows handle-bound promotion semantics")
    def test_promotion_moves_owned_file_into_captured_parent_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            source = root / "owned.staging"
            destination = root / "installed.bin"
            source.write_bytes(b"owned")

            promote_owned_path_no_replace(
                source,
                source.lstat(),
                destination,
                root.lstat(),
                directory=False,
            )

            self.assertFalse(source.exists())
            self.assertEqual(destination.read_bytes(), b"owned")

    @unittest.skipUnless(os.name == "nt", "Windows handle-bound promotion semantics")
    def test_promotion_moves_owned_directory_into_captured_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            source = root / "owned.staging"
            destination = root / "installed"
            source.mkdir()
            (source / "marker.txt").write_bytes(b"owned")

            promote_owned_path_no_replace(
                source,
                source.lstat(),
                destination,
                root.lstat(),
                directory=True,
            )

            self.assertFalse(source.exists())
            self.assertEqual((destination / "marker.txt").read_bytes(), b"owned")

    @unittest.skipUnless(os.name == "nt", "Windows handle-bound promotion semantics")
    def test_promotion_collision_preserves_owned_source_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            source = root / "owned.staging"
            destination = root / "installed.bin"
            source.write_bytes(b"owned")
            destination.write_bytes(b"existing")

            with self.assertRaises(FileExistsError):
                promote_owned_path_no_replace(
                    source,
                    source.lstat(),
                    destination,
                    root.lstat(),
                    directory=False,
                )

            self.assertEqual(source.read_bytes(), b"owned")
            self.assertEqual(destination.read_bytes(), b"existing")

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor promotion semantics")
    def test_posix_promotion_retains_replacement_inserted_after_source_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            source = root / "owned.staging"
            replacement = root / "replacement.tmp"
            displaced = root / "displaced.tmp"
            destination = root / "installed.bin"
            source.write_bytes(b"owned")
            replacement.write_bytes(b"replacement")
            source_identity = source.lstat()
            original_promote = _filesystem_capability._promote_descriptor_no_replace

            def replace_source_after_open(*args: object) -> None:
                source.rename(displaced)
                replacement.rename(source)
                original_promote(*args)

            with mock.patch.object(
                _filesystem_capability,
                "_promote_descriptor_no_replace",
                side_effect=replace_source_after_open,
            ), self.assertRaises(OSError) as raised:
                promote_owned_path_no_replace(
                    source,
                    source_identity,
                    destination,
                    root.lstat(),
                    directory=False,
                )

            self.assertFalse(destination.exists())
            self.assertEqual(raised.exception.errno, errno.ENOTSUP)
            self.assertEqual(source.read_bytes(), b"replacement")
            self.assertEqual(displaced.read_bytes(), b"owned")

    def test_posix_promotion_is_unconditionally_unsupported(self) -> None:
        with mock.patch.object(
            _filesystem_capability.os,
            "name",
            "posix",
        ), self.assertRaises(OSError) as raised:
            _filesystem_capability._promote_descriptor_no_replace(
                1,
                2,
                "installed.bin",
            )

        self.assertEqual(raised.exception.errno, errno.ENOTSUP)

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

    def test_posix_fdopen_base_exception_closes_raw_output_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            destination = root / "owned.tmp"
            parent = mock.Mock(descriptor=123)

            with mock.patch.object(
                _filesystem_capability.os,
                "name",
                "posix",
            ), mock.patch.object(
                _filesystem_capability._DirectoryCapability,
                "capture",
                return_value=parent,
            ), mock.patch.object(
                _filesystem_capability.os,
                "open",
                return_value=456,
            ), mock.patch.object(
                _filesystem_capability.os,
                "fdopen",
                side_effect=KeyboardInterrupt("fdopen interrupted"),
            ), mock.patch.object(
                _filesystem_capability.os,
                "close",
            ) as close_descriptor, self.assertRaises(KeyboardInterrupt):
                open_exclusive_output(destination, root.lstat())

            close_descriptor.assert_called_once_with(456)
            parent.close.assert_called_once_with()

    @unittest.skipUnless(os.name == "nt", "Windows handle-bound disposition semantics")
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

    def test_posix_cleanup_retains_owned_path_without_delete_primitives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            owned_file = Path(temporary_directory) / "owned.tmp"
            owned_file.write_bytes(b"owned")

            with mock.patch.object(
                _filesystem_capability.os,
                "name",
                "posix",
            ), mock.patch.object(
                _filesystem_capability,
                "_open_delete_descriptor",
                side_effect=AssertionError("delete capability opened"),
            ) as open_delete, mock.patch.object(
                _filesystem_capability.os,
                "unlink",
                side_effect=AssertionError("unlink called"),
            ) as unlink, mock.patch.object(
                _filesystem_capability.os,
                "rmdir",
                side_effect=AssertionError("rmdir called"),
            ) as rmdir:
                removed = remove_owned_path(
                    owned_file,
                    owned_file.lstat(),
                    directory=False,
                )

            self.assertFalse(removed)
            self.assertEqual(owned_file.read_bytes(), b"owned")
            open_delete.assert_not_called()
            unlink.assert_not_called()
            rmdir.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows handle-bound disposition semantics")
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
