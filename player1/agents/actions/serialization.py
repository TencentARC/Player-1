"""Canonical serialization for validated model action payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from typing import Any

_XML_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_PARAMETER_CLOSE_PATTERN = re.compile(r"</parameter>", re.IGNORECASE)
ACTION_FORMAT_QWEN3_CODER_XML = "qwen3_coder_xml"


def require_action_format(action_format: str) -> str:
    """Return the one supported model action serialization or fail fast."""

    normalized = str(action_format or "").strip()
    if normalized != ACTION_FORMAT_QWEN3_CODER_XML:
        raise ValueError(f"Unsupported action_format {action_format!r}; expected {ACTION_FORMAT_QWEN3_CODER_XML}")
    return normalized


def _require_payload(payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise TypeError("action payload must be a mapping")
    tool_name = payload.get("tool_name")
    arguments = payload.get("arguments")
    if (
        not isinstance(tool_name, str)
        or _XML_IDENTIFIER_PATTERN.fullmatch(tool_name) is None
        or not isinstance(arguments, Mapping)
    ):
        raise ValueError("action payload requires a valid tool_name and mapping arguments")

    normalized_arguments: dict[str, Any] = {}
    for raw_name, value in arguments.items():
        if not isinstance(raw_name, str) or _XML_IDENTIFIER_PATTERN.fullmatch(raw_name) is None:
            raise ValueError(f"Invalid action argument name: {raw_name!r}")
        normalized_arguments[raw_name] = value
    return tool_name, normalized_arguments


def _ordered_arguments(
    arguments: Mapping[str, Any],
    argument_order: Sequence[str] | None,
) -> list[tuple[str, Any]]:
    if not argument_order:
        return list(arguments.items())
    ordered_names = [name for name in argument_order if name in arguments]
    ordered_names.extend(name for name in arguments if name not in ordered_names)
    return [(name, arguments[name]) for name in ordered_names]


def _render_native_parameter_value(value: Any) -> str:
    if isinstance(value, str):
        if _PARAMETER_CLOSE_PATTERN.search(value):
            raise ValueError("String action arguments cannot contain </parameter>")
        try:
            json.loads(value.strip())
        except json.JSONDecodeError:
            return value
        # Preserve string type for values such as "true" or "1", which the
        # native parser would otherwise decode as a JSON scalar.
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_action_payload(
    action_format: str,
    payload: Mapping[str, Any],
    *,
    argument_order: Sequence[str] | None = None,
) -> str:
    """Render one validated payload as exactly one canonical action block."""

    require_action_format(action_format)
    tool_name, arguments = _require_payload(payload)
    ordered_arguments = _ordered_arguments(arguments, argument_order)

    lines = ["<tool_call>", f"<function={tool_name}>"]
    for name, value in ordered_arguments:
        lines.extend(
            [
                f"<parameter={name}>",
                _render_native_parameter_value(value),
                "</parameter>",
            ]
        )
    lines.extend(["</function>", "</tool_call>"])
    return "\n".join(lines)


__all__ = [
    "ACTION_FORMAT_QWEN3_CODER_XML",
    "render_action_payload",
    "require_action_format",
]
