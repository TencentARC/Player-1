"""Portable paths in published gameplay datasets."""

from pathlib import PurePosixPath, PureWindowsPath


def is_canonical_relative_posix_path(value: object, *, suffix: str | None = None) -> bool:
    """Return whether ``value`` is a portable, canonical relative POSIX path."""

    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        bool(path.parts)
        and not path.is_absolute()
        and not PureWindowsPath(value).drive
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
        and (suffix is None or path.suffix.casefold() == suffix.casefold())
    )
