"""Shared helpers for catalog YAML parsing."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
import math
from pathlib import Path
from typing import Any

import yaml


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file and require a mapping at the root."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"Invalid YAML structure in {path}: root must be a mapping")
    return dict(data)


def require_mapping(value: Any, *, owner: str) -> dict[str, Any]:
    """Return a plain mapping or reject a malformed catalog value."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{owner} must be a mapping.")
    return dict(value)


def validate_mapping_fields(
    raw: Mapping[str, Any],
    *,
    owner: str,
    supported_fields: Collection[str],
    deprecated_fields: Mapping[str, str] | None = None,
) -> None:
    """Reject deprecated and unknown keys at one catalog schema boundary."""
    deprecated = deprecated_fields or {}
    for field, replacement in deprecated.items():
        if field in raw:
            raise ValueError(f"{owner} field {field!r} is no longer supported; use {replacement!r}.")

    supported = set(supported_fields)
    unknown = sorted((field for field in raw if field not in supported), key=str)
    if unknown:
        raise ValueError(f"{owner} field {unknown[0]!r} is not supported.")


def require_text(value: Any, *, owner: str) -> str:
    """Require an exact YAML string without coercing other scalar types."""
    if not isinstance(value, str):
        raise ValueError(f"{owner} must be text.")
    return value


def require_nonempty_text(value: Any, *, owner: str) -> str:
    """Require text containing at least one non-whitespace character."""
    text = require_text(value, owner=owner).strip()
    if not text:
        raise ValueError(f"{owner} must be non-empty text.")
    return text


def require_optional_text(value: Any, *, owner: str) -> str | None:
    """Return stripped text or an explicitly supplied null."""
    if value is None:
        return None
    text = require_text(value, owner=owner).strip()
    return text or None


def require_bool(value: Any, *, owner: str) -> bool:
    """Require a YAML boolean rather than interpreting truthy values."""
    if not isinstance(value, bool):
        raise ValueError(f"{owner} must be true or false.")
    return value


def require_float(value: Any, *, owner: str, positive: bool = False) -> float:
    """Require a finite YAML number, optionally constrained above zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{owner} must be a number.")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{owner} must be finite.")
    if positive and parsed <= 0.0:
        raise ValueError(f"{owner} must be greater than zero.")
    return parsed


def require_optional_float(value: Any, *, owner: str) -> float | None:
    """Require a finite YAML number or accept an explicit null."""
    if value is None:
        return None
    return require_float(value, owner=owner)


def require_int(value: Any, *, owner: str, positive: bool = False) -> int:
    """Require an exact YAML integer, optionally constrained above zero."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{owner} must be an integer.")
    if positive and value <= 0:
        raise ValueError(f"{owner} must be greater than zero.")
    return value


def require_optional_int(value: Any, *, owner: str, positive: bool = False) -> int | None:
    """Require an exact YAML integer or accept an explicit null."""
    if value is None:
        return None
    return require_int(value, owner=owner, positive=positive)


def format_known_ids(known: Iterable[str], *, limit: int = 8) -> str:
    """Preview a truncated list of known catalog ids for error messages."""
    known_list = list(known)
    preview = ", ".join(known_list[:limit])
    suffix = ", ..." if len(known_list) > limit else ""
    return f"{preview}{suffix}" if preview else "(none)"
