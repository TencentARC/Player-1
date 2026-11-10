"""Read and validate the frozen MineDojo task catalog."""

from pathlib import Path
from typing import Any

from .schema import load_manifest_file

DEFAULT_COMPILED_MANIFEST_PATH = Path(__file__).with_name("data") / "compiled_manifest.json"


def load_compiled_manifest(path: str | Path | None = None) -> dict[str, Any]:
    """Load the published task artifact and enforce its schema and counts."""
    return load_manifest_file(path or DEFAULT_COMPILED_MANIFEST_PATH)


__all__ = ["DEFAULT_COMPILED_MANIFEST_PATH", "load_compiled_manifest"]
