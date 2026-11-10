"""Filesystem snapshots and metadata validation for published gameplay datasets."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True, slots=True)
class PlayerOneControlReleaseFileSnapshot:
    """Filesystem identity for one validated release member."""

    path: Path
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int

    @staticmethod
    def _changed_ns(info: os.stat_result) -> int:
        return 0 if os.name == "nt" else info.st_ctime_ns

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            PlayerOneControlReleaseFileSnapshot._changed_ns(info),
        )

    @classmethod
    def capture(cls, path: Path) -> PlayerOneControlReleaseFileSnapshot:
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        try:
            info = path.lstat()
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"cannot inspect Player-1 Control release member: {path}") from error
        if (
            path.is_symlink()
            or bool(getattr(info, "st_file_attributes", 0) & reparse)
            or not stat.S_ISREG(info.st_mode)
            or not resolved.is_file()
        ):
            raise ValueError(f"Player-1 Control release member must be a regular file: {path}")
        return cls(resolved, *cls._identity(info))

    def open_metadata_verified(self) -> BinaryIO:
        stream: BinaryIO | None = None
        try:
            stream = self.path.open("rb")
            opened = os.fstat(stream.fileno())
            current = self.path.lstat()
        except OSError as error:
            if stream is not None:
                stream.close()
            raise ValueError(f"cannot open frozen Player-1 Control release member: {self.path}") from error
        expected = (self.device, self.inode, self.size, self.modified_ns, self.changed_ns)
        if self._identity(opened) != expected or self._identity(current) != expected:
            stream.close()
            raise ValueError(f"Player-1 Control release member changed after validation: {self.path}")
        return stream

    def assert_metadata_current(self) -> None:
        try:
            info = self.path.lstat()
        except OSError as error:
            raise ValueError(f"cannot inspect frozen Player-1 Control release member: {self.path}") from error
        expected = (self.device, self.inode, self.size, self.modified_ns, self.changed_ns)
        if self._identity(info) != expected:
            raise ValueError(f"Player-1 Control release member changed after validation: {self.path}")

    def assert_current(self) -> None:
        self.assert_metadata_current()
