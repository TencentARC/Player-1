"""Semantic control utilities for GameWorld benchmarks."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger(__name__)

_CONTROL_ID_KEY = "tool_name"
_CONTROL_ID_KEYS = (_CONTROL_ID_KEY,)
_NON_ARGUMENT_KEYS = set(_CONTROL_ID_KEYS) | {"arguments"}


def _extract_control_id(raw: Mapping[str, Any]) -> str | None:
    candidate = raw.get(_CONTROL_ID_KEY)
    text = str(candidate or "").strip()
    if text:
        return text
    return None


def _extract_arguments(raw: Mapping[str, Any]) -> dict[str, Any]:
    raw_arguments = raw.get("arguments")
    if isinstance(raw_arguments, Mapping):
        return dict(raw_arguments)
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            return dict(parsed)

    return {
        str(key): value
        for key, value in raw.items()
        if key not in _NON_ARGUMENT_KEYS
    }


def _apply_cell_binding(mapped: dict[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    cell_bindings = mapped.get("cell_bindings")
    if not isinstance(cell_bindings, Mapping):
        return mapped

    raw_cell = arguments.get("cell")
    cell = str(raw_cell or "").strip().lower()
    if not cell:
        return mapped

    coords = cell_bindings.get(cell)
    if not isinstance(coords, Mapping):
        return mapped

    mapped["x"] = coords.get("x")
    mapped["y"] = coords.get("y")
    mapped.pop("cell_bindings", None)
    return mapped


def _merge_runtime_arguments(
    mapped: dict[str, Any],
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    for key, value in arguments.items():
        if key in _NON_ARGUMENT_KEYS or key in mapped or value is None:
            continue
        mapped[key] = value
    return mapped


def resolve_semantic_controls(
    control_name: str | None,
    semantic_controls_map: dict[str, dict] | None,
) -> dict | None:
    """Resolve a semantic control id into a low-level action mapping."""
    if not control_name or not semantic_controls_map:
        return None

    control_key = str(control_name).strip()
    if not control_key:
        return None

    if control_key in semantic_controls_map:
        return dict(semantic_controls_map[control_key])
    return None


def map_semantic_controls_output(
    raw: dict | None,
    semantic_controls_map: dict[str, dict] | None,
) -> dict | None:
    """Map semantic-tool output into a low-level action dict."""
    if not isinstance(raw, Mapping):
        LOGGER.warning("Invalid raw action payload: %s", raw)
        return raw

    control_id = _extract_control_id(raw)
    if not control_id:
        LOGGER.warning("No control id found in raw action: %s", raw)
        return dict(raw)

    mapped = resolve_semantic_controls(control_id, semantic_controls_map)
    if not mapped:
        LOGGER.warning("No mapped control found for control id: %s", control_id)
        return dict(raw)

    arguments = _extract_arguments(raw)
    mapped = _merge_runtime_arguments(mapped, arguments)
    mapped = _apply_cell_binding(mapped, arguments)
    mapped.setdefault("semantic_controls", control_id)
    return mapped


def inspect_semantic_controls_output(
    raw: dict | None,
    semantic_controls_map: dict[str, dict] | None,
) -> dict[str, Any]:
    """Inspect whether a semantic action payload is valid and mappable."""
    if not isinstance(raw, Mapping):
        return {
            "is_valid": False,
            "reason": "invalid_payload",
            "invalid_kind": "no_function_call",
            "control_id": None,
            "mapped_action": None,
        }

    control_id = _extract_control_id(raw)
    if not control_id:
        return {
            "is_valid": False,
            "reason": "missing_tool_name",
            "invalid_kind": "no_function_call",
            "control_id": None,
            "mapped_action": None,
        }

    mapped = resolve_semantic_controls(control_id, semantic_controls_map)
    if not mapped:
        return {
            "is_valid": False,
            "reason": "unknown_tool_name",
            "invalid_kind": "out_of_space",
            "control_id": control_id,
            "mapped_action": None,
        }

    arguments = _extract_arguments(raw)
    mapped = _merge_runtime_arguments(mapped, arguments)
    mapped = _apply_cell_binding(mapped, arguments)
    mapped.setdefault("semantic_controls", control_id)
    return {
        "is_valid": True,
        "reason": "valid",
        "invalid_kind": None,
        "control_id": control_id,
        "mapped_action": mapped,
    }


__all__ = [
    "inspect_semantic_controls_output",
    "map_semantic_controls_output",
    "resolve_semantic_controls",
]
