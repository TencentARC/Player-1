"""Resolve external media tools from explicit or active-environment installs."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_TOOL_ENVIRONMENTS = {
    "ffmpeg": "PLAYER1_DATA_FFMPEG",
    "ffprobe": "PLAYER1_DATA_FFPROBE",
}


def _active_environment_candidates(tool: str) -> tuple[Path, ...]:
    """Return standard executable locations for the running Python environment."""

    executable_names = (f"{tool}.exe", tool) if os.name == "nt" else (tool,)
    prefix = Path(sys.prefix).resolve()
    directories = (
        prefix / "Library" / "bin",  # conda-forge packages on Windows
        prefix / "Scripts",  # Python/conda entry points on Windows
        prefix / "bin",  # conda/venv installs on POSIX
    )
    return tuple(directory / name for directory in directories for name in executable_names)


def resolve_media_tool(tool: str) -> str:
    """Return an explicit media-tool executable or resolve it from ``PATH``."""

    try:
        environment_name = _TOOL_ENVIRONMENTS[tool]
    except KeyError as error:
        supported = ", ".join(sorted(_TOOL_ENVIRONMENTS))
        raise ValueError(f"Unsupported media tool {tool!r}; expected one of: {supported}") from error

    override = os.environ.get(environment_name)
    if override is not None:
        value = override.strip()
        if not value:
            raise RuntimeError(f"{environment_name} is set but empty; unset it or provide an absolute executable path")
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise RuntimeError(f"{environment_name} must be an absolute executable path; got {value!r}")
        resolved = path.resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise RuntimeError(f"{environment_name} must name an existing executable file; got {resolved}")
        return str(resolved)

    resolved = shutil.which(tool)
    if resolved is not None:
        return resolved

    for candidate in _active_environment_candidates(tool):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())

    raise RuntimeError(
        f"{tool} is required for video normalization but was not found on PATH "
        f"or in the active Python environment ({Path(sys.prefix).resolve()}). "
        f"Install FFmpeg in the active environment or set {environment_name} to an absolute executable path."
    )


def resolve_ffmpeg() -> str:
    return resolve_media_tool("ffmpeg")


def resolve_ffprobe() -> str:
    return resolve_media_tool("ffprobe")
