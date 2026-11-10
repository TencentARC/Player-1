"""Validate and compile one Player-1 Control frame into a game-step action."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

from .control import compile_frame, player1_control_tool_calls, validate_cross_arguments
from .control import ACTION_SPACE_MODE

_ARGUMENT_SCHEMA_KEY = "argument_schema"
_ACTION_SPACE_MODE_KEY = "_action_space_mode"


def _extract_tool_name(raw: Mapping[str, Any]) -> str | None:
    candidate = raw.get("tool_name")
    return candidate.strip() if isinstance(candidate, str) and candidate.strip() else None


def _extract_arguments(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    raw_arguments = raw.get("arguments")
    return dict(raw_arguments) if isinstance(raw_arguments, Mapping) else None


def _find_non_finite_numbers(value: Any, path: tuple[str | int, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(value, float) and not math.isfinite(value):
        return [{"code": "non_finite_number", "path": list(path), "message": "number must be finite"}]
    if isinstance(value, Mapping):
        return [error for key, item in value.items() for error in _find_non_finite_numbers(item, (*path, str(key)))]
    if isinstance(value, list):
        return [error for index, item in enumerate(value) for error in _find_non_finite_numbers(item, (*path, index))]
    return []


def _validate_arguments(mapped: Mapping[str, Any], arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
    schema = mapped.get(_ARGUMENT_SCHEMA_KEY)
    if not isinstance(schema, Mapping):
        raise TypeError("Unified action mapping is missing argument_schema")

    errors = _find_non_finite_numbers(arguments)
    schema_errors = sorted(
        Draft202012Validator(dict(schema)).iter_errors(arguments),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors.extend(
        {
            "code": str(error.validator),
            "path": list(error.absolute_path),
            "message": error.message,
        }
        for error in schema_errors
    )
    return errors


def _invalid_action_inspection(
    reason: str,
    invalid_kind: str,
    *,
    tool_name: str | None = None,
    argument_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inspection = {
        "is_valid": False,
        "reason": reason,
        "invalid_kind": invalid_kind,
        "tool_name": tool_name,
        "mapped_action": None,
    }
    if argument_errors is not None:
        inspection["argument_errors"] = argument_errors
    return inspection


def inspect_unified_action_output(
    frame: Mapping[str, Any] | None,
    unified_action_space_map: dict[str, dict] | None,
) -> dict[str, Any]:
    """Validate and compile one complete Player-1 Control frame envelope."""

    if not isinstance(frame, Mapping):
        return _invalid_action_inspection("invalid_payload", "no_function_call")

    action_space_mode = str(frame.get("action_space_mode") or "").strip()
    if action_space_mode != ACTION_SPACE_MODE:
        return _invalid_action_inspection("invalid_control_frame", "invalid_arguments")

    tool_calls = player1_control_tool_calls(frame)
    if tool_calls is None:
        return _invalid_action_inspection("invalid_control_frame", "invalid_arguments")

    action_map = unified_action_space_map or {}
    definitions_by_tool: dict[str, Mapping[str, Any]] = {}
    arguments_by_tool: dict[str, Mapping[str, Any]] = {}
    argument_errors: list[dict[str, Any]] = []

    for tool_call in tool_calls:
        tool_name = _extract_tool_name(tool_call)
        if tool_name is None:
            return _invalid_action_inspection("invalid_control_frame", "invalid_arguments")
        definition = action_map.get(tool_name)
        if not isinstance(definition, Mapping):
            return _invalid_action_inspection("unknown_tool_name", "out_of_space", tool_name=tool_name)
        if str(definition.get(_ACTION_SPACE_MODE_KEY) or "").strip() != action_space_mode:
            raise ValueError(
                f"Control tool mapping has the wrong action-space mode for {action_space_mode!r}: {tool_name}"
            )

        arguments = _extract_arguments(tool_call)
        if arguments is None:
            return _invalid_action_inspection("invalid_control_frame", "invalid_arguments", tool_name=tool_name)
        definitions_by_tool[tool_name] = definition
        arguments_by_tool[tool_name] = arguments
        argument_errors.extend(
            {
                **error,
                "path": [tool_name, *error["path"]],
            }
            for error in _validate_arguments(definition, arguments)
        )

    if not argument_errors:
        argument_errors = validate_cross_arguments(arguments_by_tool)
    if argument_errors:
        return _invalid_action_inspection(
            "invalid_arguments",
            "invalid_arguments",
            tool_name="control",
            argument_errors=argument_errors,
        )

    durations = {definition.get("duration_ms", 200) for definition in definitions_by_tool.values()}
    if len(durations) != 1:
        raise ValueError(f"{action_space_mode} channel mappings must use one duration_ms")
    tool_name, mapped_action = compile_frame(
        arguments_by_tool,
        duration_ms=int(next(iter(durations))),
    )
    return {
        "is_valid": True,
        "reason": "valid",
        "invalid_kind": None,
        "tool_name": tool_name,
        "mapped_action": mapped_action,
    }


__all__ = ["inspect_unified_action_output"]
