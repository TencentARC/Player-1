"""Shared helpers for catalog YAML parsing."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

_TRUTHY_STRINGS = {"1", "true", "yes", "on"}


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file and require a mapping at the root."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Invalid YAML structure in {path}: root must be a mapping")
    return dict(data)


def as_mapping(value: Any) -> dict[str, Any]:
    """Coerce a value into a plain dict when possible."""
    return dict(value) if isinstance(value, Mapping) else {}


def as_mapping_list(value: Any) -> list[dict[str, Any]]:
    """Keep only mapping items from a list-like value."""
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def as_text(value: Any, *, default: str = "") -> str:
    """Coerce a value to text."""
    if value is None:
        return default
    return str(value)


def as_optional_text(value: Any) -> str | None:
    """Return stripped text or None when blank."""
    text = as_text(value).strip()
    return text or None


def as_bool(value: Any, *, default: bool = False) -> bool:
    """Coerce common YAML and string booleans."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_STRINGS
    return bool(value)


def _coerce_number(
    value: Any,
    cast: Callable[[Any], Any],
    *,
    default: Any = None,
) -> Any:
    if value is None or value == "":
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, *, default: float = 0.0) -> float:
    """Coerce a numeric value to float, falling back to default."""
    return float(_coerce_number(value, float, default=default))


def as_int(value: Any, *, default: int = 0) -> int:
    """Coerce a numeric value to int, falling back to default."""
    return int(_coerce_number(value, int, default=default))


def as_string_list(value: Any) -> list[str]:
    """Coerce a list-like value to a list of non-empty strings."""
    if isinstance(value, (str, bytes)):
        items: Iterable[Any] = [value]
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        items = value
    else:
        return []

    strings: list[str] = []
    for item in items:
        text = as_optional_text(item)
        if text:
            strings.append(text)
    return strings


def as_string_set(value: Any) -> set[str]:
    """Coerce a list-like value to a set of strings."""
    return set(as_string_list(value))


def as_string_float_mapping(value: Any) -> dict[str, float]:
    """Coerce a mapping with string keys and float values."""
    if not isinstance(value, Mapping):
        return {}

    result: dict[str, float] = {}
    for key, raw_value in value.items():
        text_key = as_optional_text(key)
        if not text_key:
            continue
        result[text_key] = as_float(raw_value)
    return result
