"""Provider-specific tool schemas for semantic action calling."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

ActionSpec = Mapping[str, Any]
ToolFormatter = Callable[[str, str, dict[str, Any]], dict[str, Any]]

_REASONING_PROPERTY = {
    "type": "string",
    "description": "Short rationale for the action.",
}
_CELL_PROPERTY = {
    "type": "string",
    "description": "Cell id, e.g., a1, i9.",
}
_TEXT_PROPERTY = {
    "type": "string",
    "description": "Text to type (use \\n for Enter).",
}


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe_preserve_order(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _iter_action_specs(
    action_specs: Sequence[dict] | None,
) -> list[tuple[str, str, dict[str, Any]]]:
    normalized: list[tuple[str, str, dict[str, Any]]] = []
    for raw_spec in action_specs or []:
        spec = _as_mapping(raw_spec)
        action_id = str(spec.get("id") or "").strip()
        if not action_id:
            continue
        normalized.append(
            (
                action_id,
                str(spec.get("description") or "").strip(),
                spec,
            )
        )
    return normalized


def _build_action_parameters(
    action: ActionSpec | None,
    *,
    require_reasoning: bool,
    require_text: bool,
    forbid_extra_properties: bool = False,
) -> dict[str, Any]:
    spec = _as_mapping(action)
    binding = _as_mapping(spec.get("binding"))
    raw_parameters = spec.get("parameters")

    properties: dict[str, Any] = {}
    required: list[str] = []

    parameters = _as_mapping(raw_parameters)
    if parameters:
        nested_properties = _as_mapping(parameters.get("properties"))
        if nested_properties:
            properties.update(nested_properties)
            required.extend(_string_list(parameters.get("required")))
        else:
            properties.update(parameters)
            required.extend(_string_list(spec.get("required")))

    properties.setdefault("reasoning", dict(_REASONING_PROPERTY))
    if require_reasoning:
        required.append("reasoning")

    if binding.get("cell_param"):
        properties.setdefault("cell", dict(_CELL_PROPERTY))
        required.append("cell")

    if str(binding.get("action") or "").strip().lower() == "type":
        properties.setdefault("text", dict(_TEXT_PROPERTY))
        if require_text:
            required.append("text")

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    deduped_required = _dedupe_preserve_order(required)
    if deduped_required:
        schema["required"] = deduped_required
    if forbid_extra_properties:
        schema["additionalProperties"] = False
    return schema


def _build_tools(
    action_specs: Sequence[dict] | None,
    *,
    require_reasoning: bool,
    require_text: bool,
    forbid_extra_properties: bool,
    formatter: ToolFormatter,
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for action_id, description, spec in _iter_action_specs(action_specs):
        parameters = _build_action_parameters(
            spec,
            require_reasoning=require_reasoning,
            require_text=require_text,
            forbid_extra_properties=forbid_extra_properties,
        )
        tools.append(formatter(action_id, description, parameters))
    return tools


def build_gemini_action_tools(action_specs: Sequence[dict]) -> list[dict]:
    return _build_tools(
        action_specs,
        require_reasoning=True,
        require_text=True,
        forbid_extra_properties=False,
        formatter=lambda name, description, parameters: {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    )


def build_openai_action_tools(action_specs: Sequence[dict]) -> list[dict]:
    return _build_tools(
        action_specs,
        require_reasoning=True,
        require_text=True,
        forbid_extra_properties=True,
        formatter=lambda name, description, parameters: {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": parameters,
            "strict": True,
        },
    )


def build_claude_action_tools(action_specs: Sequence[dict]) -> list[dict]:
    return _build_tools(
        action_specs,
        require_reasoning=True,
        require_text=True,
        forbid_extra_properties=True,
        formatter=lambda name, description, parameters: {
            "name": name,
            "description": description,
            "input_schema": parameters,
            "strict": True,
        },
    )


def build_glm_action_tools(action_specs: Sequence[dict]) -> list[dict]:
    return _build_tools(
        action_specs,
        require_reasoning=True,
        require_text=True,
        forbid_extra_properties=False,
        formatter=lambda name, description, parameters: {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
    )


def build_kimi_action_tools(action_specs: Sequence[dict]) -> list[dict]:
    return _build_tools(
        action_specs,
        require_reasoning=False,
        require_text=True,
        forbid_extra_properties=False,
        formatter=lambda name, description, parameters: {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
    )


__all__ = [
    "build_claude_action_tools",
    "build_gemini_action_tools",
    "build_glm_action_tools",
    "build_kimi_action_tools",
    "build_openai_action_tools",
]
