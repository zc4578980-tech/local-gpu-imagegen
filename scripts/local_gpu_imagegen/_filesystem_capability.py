from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CREATE_FILE = _KERNEL32.CreateFileW
    _CREATE_FILE.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CREATE_FILE.restype = wintypes.HANDLE
    _GET_FINAL_PATH = _KERNEL32.GetFinalPathNameByHandleW
    _GET_FINAL_PATH.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _GET_FINAL_PATH.restype = wintypes.DWORD
    _SET_FILE_INFORMATION = _KERNEL32.SetFileInformationByHandle
    _SET_FILE_INFORMATION.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _SET_FILE_INFORMATION.restype = wintypes.BOOL
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = [wintypes.HANDLE]
    _CLOSE_HANDLE.restype = wintypes.BOOL

    _DELETE = 0x00010000
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004
    _OPEN_EXISTING = 3
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_DISPOSITION_INFO_CLASS = 4
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]


def _safe_kind(path_stat: os.stat_result, *, directory: bool) -> bool:
    expected_kind = stat.S_ISDIR(path_stat.st_mode) if directory else stat.S_ISREG(
        path_stat.st_mode
    )
    return (
        expected_kind
        and not stat.S_ISLNK(path_stat.st_mode)
        and not bool(getattr(path_stat, "st_file_attributes", 0) & _REPARSE_POINT)
    )


def _normalized_final_path(value: str) -> str:
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
    return os.path.normcase(os.path.abspath(os.path.normpath(value)))


def _final_path_for_descriptor(descriptor: int) -> str:
    if os.name == "nt":
        handle = msvcrt.get_osfhandle(descriptor)
        required = _GET_FINAL_PATH(handle, None, 0, 0)
        if not required:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = _GET_FINAL_PATH(handle, buffer, len(buffer), 0)
        if not written or written >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        return _normalized_final_path(buffer.value)

    descriptor_path = Path("/proc/self/fd") / str(descriptor)
    try:
        return _normalized_final_path(os.readlink(descriptor_path))
    except OSError as error:
        raise OSError("final descriptor path is unavailable") from error


def _windows_descriptor(
    path: Path,
    *,
    access: int,
    directory: bool,
) -> int:
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    handle = _CREATE_FILE(
        str(path),
        access,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except BaseException:
        _CLOSE_HANDLE(handle)
        raise
    return descriptor


def _open_directory_descriptor(path: Path) -> int:
    if os.name == "nt":
        return _windows_descriptor(
            path,
            access=_FILE_READ_ATTRIBUTES,
            directory=True,
        )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags)


@dataclass(slots=True)
class _DirectoryCapability:
    path: Path
    identity: os.stat_result
    descriptor: int

    @classmethod
    def capture(
        cls,
        path: Path,
        expected_identity: os.stat_result,
    ) -> _DirectoryCapability:
        descriptor = _open_directory_descriptor(path)
        try:
            opened_stat = os.fstat(descriptor)
            if not _safe_kind(opened_stat, directory=True) or not os.path.samestat(
                expected_identity,
                opened_stat,
            ):
                raise OSError("directory capability identity mismatch")
            _final_path_for_descriptor(descriptor)
            return cls(path=path, identity=opened_stat, descriptor=descriptor)
        except BaseException:
            os.close(descriptor)
            raise

    def require_direct_child(self, descriptor: int, expected_name: str | None) -> None:
        child_final = _final_path_for_descriptor(descriptor)
        directory_final = _final_path_for_descriptor(self.descriptor)
        if os.path.dirname(child_final) != directory_final:
            raise OSError("opened descriptor escaped its captured directory")
        if expected_name is not None and os.path.basename(child_final) != os.path.normcase(
            expected_name
        ):
            raise OSError("opened descriptor name changed")

    def close(self) -> None:
        os.close(self.descriptor)


def open_exclusive_output(
    path: Path,
    parent_identity: os.stat_result,
) -> tuple[BinaryIO, os.stat_result]:
    """Open one new file and prove its descriptor is a child of the captured parent."""
    parent = _DirectoryCapability.capture(path.parent, parent_identity)
    stream: BinaryIO | None = None
    opened_stat: os.stat_result | None = None
    try:
        if os.name == "nt":
            stream = path.open("x+b")
        else:
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(path.name, flags, 0o600, dir_fd=parent.descriptor)
            stream = os.fdopen(descriptor, "w+b")
        opened_stat = os.fstat(stream.fileno())
        current_stat = path.lstat()
        if (
            not _safe_kind(opened_stat, directory=False)
            or opened_stat.st_nlink != 1
            or not os.path.samestat(opened_stat, current_stat)
        ):
            raise OSError("exclusive output identity changed while opening")
        parent.require_direct_child(stream.fileno(), path.name)
        return stream, opened_stat
    except BaseException:
        if stream is not None:
            stream.close()
        if opened_stat is not None:
            remove_owned_path(path, opened_stat, directory=False)
        raise
    finally:
        parent.close()


def open_bound_temporary(
    directory: Path,
    directory_identity: os.stat_result,
) -> BinaryIO:
    """Create a delete-on-close snapshot and validate its handle before any writes."""
    parent = _DirectoryCapability.capture(directory, directory_identity)
    stream: BinaryIO | None = None
    try:
        stream = tempfile.SpooledTemporaryFile(max_size=1, mode="w+b", dir=directory)
        stream.rollover()
        parent.require_direct_child(stream.fileno(), None)
        return stream
    except BaseException:
        if stream is not None:
            stream.close()
        raise
    finally:
        parent.close()


@dataclass(slots=True)
class _DeleteCapability:
    descriptor: int
    parent_descriptor: int | None = None
    name: str | None = None
    directory: bool = False

    def close(self) -> None:
        os.close(self.descriptor)
        if self.parent_descriptor is not None:
            os.close(self.parent_descriptor)


def _open_delete_descriptor(path: Path, *, directory: bool) -> _DeleteCapability:
    if os.name == "nt":
        return _DeleteCapability(
            descriptor=_windows_descriptor(
                path,
                access=_DELETE | _FILE_READ_ATTRIBUTES,
                directory=directory,
            ),
            directory=directory,
        )

    parent_descriptor = _open_directory_descriptor(path.parent)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if directory:
            flags |= getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
    except BaseException:
        os.close(parent_descriptor)
        raise
    return _DeleteCapability(
        descriptor=descriptor,
        parent_descriptor=parent_descriptor,
        name=path.name,
        directory=directory,
    )


def _delete_open_descriptor(capability: _DeleteCapability) -> bool:
    if os.name == "nt":
        disposition = _FileDispositionInfo(True)
        handle = msvcrt.get_osfhandle(capability.descriptor)
        return bool(
            _SET_FILE_INFORMATION(
                handle,
                _FILE_DISPOSITION_INFO_CLASS,
                ctypes.byref(disposition),
                ctypes.sizeof(disposition),
            )
        )

    if capability.parent_descriptor is None or capability.name is None:
        return False
    try:
        current_stat = os.stat(
            capability.name,
            dir_fd=capability.parent_descriptor,
            follow_symlinks=False,
        )
        if not os.path.samestat(current_stat, os.fstat(capability.descriptor)):
            return False
        if capability.directory:
            os.rmdir(capability.name, dir_fd=capability.parent_descriptor)
        else:
            os.unlink(capability.name, dir_fd=capability.parent_descriptor)
        return True
    except OSError:
        return False


def remove_owned_path(
    path: Path,
    identity: os.stat_result,
    *,
    directory: bool,
) -> bool:
    """Delete only the object bound to an opened capability; otherwise retain it."""
    try:
        capability = _open_delete_descriptor(path, directory=directory)
    except OSError:
        return False
    try:
        opened_stat = os.fstat(capability.descriptor)
        if not _safe_kind(opened_stat, directory=directory) or not os.path.samestat(
            identity,
            opened_stat,
        ):
            return False
        return _delete_open_descriptor(capability)
    finally:
        capability.close()
