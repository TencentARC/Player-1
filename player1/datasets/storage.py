"""Read-only local/S3 access for immutable SFT releases (no dataset staging)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

Location = Path | str


def is_s3(value: Location) -> bool:
    return isinstance(value, str) and value.startswith("s3://")


def location(value: str | os.PathLike[str]) -> Location:
    raw = str(value)
    if is_s3(raw):
        parsed = urlsplit(raw)
        key = parsed.path.removeprefix("/").rstrip("/")
        if (
            not parsed.netloc or any(c in parsed.netloc for c in "@:\\")
            or parsed.query or parsed.fragment or not key or "\\" in key
            or any(part in {"", ".", ".."} for part in key.split("/"))
        ):
            raise ValueError("SFT S3 root must be a canonical s3://bucket/prefix URI without credentials or query")
        return f"s3://{parsed.netloc}/{key}"
    if "://" in raw:
        raise ValueError("SFT data supports only local paths and s3:// URIs")
    return Path(value).expanduser().resolve()


def child(root: Location, relative: str) -> Location:
    path = PurePosixPath(relative)
    if path.is_absolute() or "\\" in relative or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise ValueError("SFT member must be a canonical relative path")
    return f"{root}/{relative}" if is_s3(root) else root / relative


def member_name(value: Location) -> str:
    return str(value).rsplit("/", 1)[-1] if is_s3(value) else value.name


@lru_cache(maxsize=4)
def _s3_filesystem(pid: int):
    # Cache clients only within the process that created them.
    import pyarrow.fs as fs

    return fs.S3FileSystem(region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2")


def open_input(value: Location):
    if is_s3(value):
        return _s3_filesystem(os.getpid()).open_input_file(value.removeprefix("s3://"))
    return value.open("rb")


def read_bytes(value: Location) -> bytes:
    with open_input(value) as stream:
        return stream.read()


def file_sizes(root: Location, *, recursive: bool = False) -> dict[str, int]:
    """List relative file names/sizes; S3 listing avoids one HEAD per image."""
    if is_s3(root):
        import pyarrow.fs as fs

        prefix = root.removeprefix("s3://")
        infos = _s3_filesystem(os.getpid()).get_file_info(fs.FileSelector(prefix, recursive=recursive))
        return {info.path.removeprefix(prefix + "/"): info.size for info in infos if info.type == fs.FileType.File}
    paths = root.rglob("*") if recursive else root.iterdir()
    return {path.relative_to(root).as_posix(): path.stat().st_size for path in paths if path.is_file()}


def _object_identity(stream) -> tuple[int, str, str]:
    metadata = stream.metadata() or {}
    etag = metadata.get("ETag", b"").decode()
    version = metadata.get("VersionId", b"").decode()
    if not etag:
        raise ValueError("SFT S3 object has no ETag; cannot freeze release identity")
    return stream.size(), etag, version


@dataclass(frozen=True, slots=True)
class S3ReleaseFileSnapshot:
    path: str
    size: int
    etag: str
    version_id: str

    @classmethod
    def capture(cls, path: str) -> S3ReleaseFileSnapshot:
        with open_input(path) as stream:
            return cls(path, *_object_identity(stream))

    def open_metadata_verified(self):
        stream = open_input(self.path)
        try:
            if _object_identity(stream) != (self.size, self.etag, self.version_id):
                raise ValueError(f"Player-1 Control S3 release member changed after validation: {self.path}")
        except BaseException:
            stream.close()
            raise
        return stream

    def assert_metadata_current(self) -> None:
        with self.open_metadata_verified():
            pass

    def assert_current(self) -> None:
        self.assert_metadata_current()

    def content_identity(self) -> dict[str, Any]:
        return {
            "name": member_name(self.path), "size_bytes": self.size, "etag": self.etag, "version_id": self.version_id,
        }
