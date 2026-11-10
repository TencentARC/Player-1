"""Validated JSON/JSONL I/O with atomic writes."""

from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from player1.datasets.paths import is_canonical_relative_posix_path as is_canonical_relative_posix_path

_TRANSIENT_WINDOWS_PERMISSION_ERRORS = frozenset({5, 32})
_WINDOWS_IO_MAX_ATTEMPTS = 8
_ResultT = TypeVar("_ResultT")


def _logical_path(path: Path) -> Path:
    """Return the ordinary absolute spelling of a Windows filesystem path."""

    if os.name != "nt":
        return path
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        return Path(f"\\\\{value[8:]}")
    if value.startswith("\\\\?\\"):
        return Path(value[4:])
    return path


def _filesystem_path(path: Path) -> Path:
    """Return a normalized OS path that preserves long paths on Windows."""

    if os.name != "nt":
        return path
    value = os.path.abspath(_logical_path(path))
    if value.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{value[2:]}")
    return Path(f"\\\\?\\{value}")


def _resolve_logical_path(path: Path, *, strict: bool = False) -> Path:
    """Resolve through the long-path filesystem view but return logical metadata."""

    logical = path.expanduser().absolute()
    return _logical_path(_filesystem_path(logical).resolve(strict=strict))


def _is_nonempty_file(path: Path) -> bool:
    """Inspect one logical path through the Windows long-path filesystem view."""

    filesystem_path = _filesystem_path(path.expanduser().absolute())
    return filesystem_path.is_file() and filesystem_path.stat().st_size > 0


def retry_transient_windows_io(operation: Callable[[], _ResultT]) -> _ResultT:
    """Bound retries for Windows sharing/access failures, then preserve the error."""

    delay = 0.01
    for attempt in range(_WINDOWS_IO_MAX_ATTEMPTS):
        try:
            return operation()
        except PermissionError as error:
            winerror = getattr(error, "winerror", None)
            # CRT-backed open() can report a sharing violation as EACCES only.
            transient = os.name == "nt" and (
                winerror in _TRANSIENT_WINDOWS_PERMISSION_ERRORS or (winerror is None and error.errno == errno.EACCES)
            )
            if not transient or attempt + 1 == _WINDOWS_IO_MAX_ATTEMPTS:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)
    raise AssertionError("bounded Windows I/O retry loop did not return or raise")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a JSONL file with source-aware errors."""
    with _filesystem_path(_resolve_logical_path(path)).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from error
            if not isinstance(payload, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            yield payload


class ImmutableArtifactError(RuntimeError):
    """An immutable metadata artifact could not be safely published."""


def _temporary_file(target: Path) -> Path:
    """Return a short sibling name that remains usable near Windows MAX_PATH."""

    return target.with_name(f".writing-{uuid.uuid4().hex}.tmp")


def canonical_json_bytes(value: Any, *, field: str) -> bytes:
    """Render one finite value with the canonical metadata encoding."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ImmutableArtifactError(f"{field} must be finite JSON") from error
    return (text + "\n").encode("utf-8")


def publish_immutable_bytes(
    path: str | Path,
    payload: bytes,
    *,
    field: str,
) -> Path:
    """Publish bytes through a sibling temporary file into a new target."""

    target_input = Path(path).expanduser()
    if not target_input.is_absolute() or target_input.parent == target_input:
        raise ImmutableArtifactError(f"{field} target must be a non-root absolute path")
    if not isinstance(payload, bytes):
        raise ImmutableArtifactError(f"{field} payload must be bytes")
    if _filesystem_path(target_input.absolute()).is_symlink():
        raise ImmutableArtifactError(f"{field} target must not be a symlink")
    target = _resolve_logical_path(target_input)
    physical_target = _filesystem_path(target)
    physical_target.parent.mkdir(parents=True, exist_ok=True)
    if physical_target.exists() or physical_target.is_symlink():
        raise ImmutableArtifactError(f"{field} target already exists: {target}")

    temporary = _temporary_file(target)
    physical_temporary = _filesystem_path(temporary)
    try:
        with physical_temporary.open("xb") as stream:
            if stream.write(payload) != len(payload):
                raise OSError("incomplete immutable artifact write")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            retry_transient_windows_io(lambda: os.link(physical_temporary, physical_target))
        except FileExistsError as error:
            raise ImmutableArtifactError(f"{field} target already exists: {target}") from error
        except OSError as error:
            raise ImmutableArtifactError(f"cannot publish {field}: {target}") from error
    finally:
        physical_temporary.unlink(missing_ok=True)
    return target


def _validate_regular_directory(root: Path, *, field: str) -> None:
    physical_root = _filesystem_path(root)
    if physical_root.is_symlink() or not physical_root.is_dir():
        raise ImmutableArtifactError(f"{field} is not a regular directory: {root}")
    has_file = False
    for entry in physical_root.rglob("*"):
        relative = entry.relative_to(physical_root).as_posix()
        if entry.is_symlink():
            raise ImmutableArtifactError(f"{field} contains a symlink: {relative}")
        if entry.is_file():
            has_file = True
        elif not entry.is_dir():
            raise ImmutableArtifactError(f"{field} contains a non-regular member: {relative}")
    if not has_file:
        raise ImmutableArtifactError(f"{field} must contain at least one file")


def _rename_no_replace(source: Path, target: Path) -> None:
    """Atomically install one directory only while its target is absent."""

    if os.name == "nt":
        os.rename(source, target)
        return

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        arguments = (-100, os.fsencode(source), -100, os.fsencode(target), 1)
    elif sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        arguments = (os.fsencode(source), os.fsencode(target), 4)
    else:
        rename = None
        arguments = ()
    if rename is None:
        raise OSError(errno.ENOTSUP, "atomic no-replace directory rename is unavailable", target)
    if rename(*arguments) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), target)


def publish_staged_immutable_directory(
    path: str | Path,
    staging_directory: str | Path,
    *,
    field: str,
) -> Path:
    """Validate and atomically rename one complete sibling staging tree."""

    target_input = Path(path).expanduser()
    staging_input = Path(staging_directory).expanduser()
    if not target_input.is_absolute() or target_input.parent == target_input:
        raise ImmutableArtifactError(f"{field} target must be a non-root absolute path")
    if not staging_input.is_absolute() or staging_input.parent == staging_input:
        raise ImmutableArtifactError(f"{field} staging directory must be a non-root absolute path")
    physical_target_input = _filesystem_path(target_input.absolute())
    physical_staging_input = _filesystem_path(staging_input.absolute())
    if physical_target_input.is_symlink() or physical_staging_input.is_symlink():
        raise ImmutableArtifactError(f"{field} target and staging directory must not be symlinks")
    target = _resolve_logical_path(target_input)
    staging = _resolve_logical_path(staging_input, strict=True)
    physical_target = _filesystem_path(target)
    physical_staging = _filesystem_path(staging)
    physical_target.parent.mkdir(parents=True, exist_ok=True)
    if staging == target:
        raise ImmutableArtifactError(f"{field} staging directory must differ from its target")
    if os.path.splitdrive(str(staging))[0].casefold() != os.path.splitdrive(str(target))[0].casefold():
        raise ImmutableArtifactError(f"{field} staging directory and target must share one volume")
    _validate_regular_directory(staging, field=f"staged {field}")
    try:
        if physical_target.exists() or physical_target.is_symlink():
            raise ImmutableArtifactError(f"{field} target already exists: {target}")
        try:
            retry_transient_windows_io(lambda: _rename_no_replace(physical_staging, physical_target))
        except FileExistsError as error:
            raise ImmutableArtifactError(f"{field} target already exists: {target}") from error
        except OSError as error:
            raise ImmutableArtifactError(f"cannot publish {field}: {target}") from error
    finally:
        if physical_staging.exists():
            shutil.rmtree(physical_staging)
    return target


def save_new_json(path: Path, value: Any) -> Path:
    return publish_immutable_bytes(path.resolve(), canonical_json_bytes(value, field=path.name), field=path.name)


def file_digest(path: Path) -> dict[str, Any]:
    import hashlib

    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Input changed while hashing: {path}")
    return {"path": str(path.resolve()), "size": after.st_size, "sha256": digest}


def fingerprint(value: Any) -> str:
    import hashlib

    return hashlib.sha256(canonical_json_bytes(value, field="input binding")).hexdigest()
