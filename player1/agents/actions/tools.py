"""Define unified keyboard and mouse action-space tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from player1.runtime.types import GameControls, RoleControls

from .control import (
    PLAYER1_CONTROL_MODEL_TOOL_ORDER,
    PLAYER1_CONTROL_RELATIVE_LIMIT,
    PLAYER1_CONTROL_RELATIVE_MOUSE_PROMPT,
)
from .devices import (
    MOUSE_SCROLL_DIRECTIONS,
    STANDARD_KEYBOARD_KEYS,
    STANDARD_MOUSE_BUTTONS,
)
from .control import require_action_space_mode

UNIFIED_ACTION_STEP_MS = 200
UNIFIED_ACTION_STEP_SECONDS = UNIFIED_ACTION_STEP_MS / 1000.0


def _duration_ms(value: float | None) -> int:
    try:
        duration = round(float(value))
    except (TypeError, ValueError):
        duration = UNIFIED_ACTION_STEP_MS
    return max(1, duration)


def _game_step_action(tool_name: str, duration_ms: int, **payload: Any) -> dict[str, Any]:
    return {
        "type": "game_step_action",
        "id": tool_name,
        "duration_ms": duration_ms,
        **payload,
    }


def _game_control_binding(control: str, duration_ms: int) -> dict[str, Any]:
    return {
        "type": "game_control",
        "control": control,
        "duration_ms": duration_ms,
    }


def _remove_empty_required(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _remove_empty_required(item) for key, item in value.items() if key != "required" or item}
    if isinstance(value, list):
        return [_remove_empty_required(item) for item in value]
    return deepcopy(value)


def _model_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Keep strict key validation at runtime without overconstraining native tools."""

    model_schema = deepcopy(schema)
    properties = model_schema.get("properties")
    if not isinstance(properties, dict):
        return model_schema
    for field_name in ("key_hold", "key_tap"):
        keys = properties.get(field_name)
        if not isinstance(keys, dict):
            continue
        items = keys.get("items")
        if isinstance(items, dict):
            items.pop("enum", None)
        # xgrammar does not support uniqueItems. Runtime admission still uses
        # the strict argument schema, so duplicate keys remain invalid.
        keys.pop("uniqueItems", None)
    return model_schema


@dataclass(slots=True)
class UnifiedActionToolSpec:
    """Canonical definition of one keyboard/mouse action tool."""

    tool_name: str
    action_space_mode: str = ""
    description: str = ""
    binding: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)

    def runtime_argument_schema(self) -> dict[str, Any]:
        """Return the strict JSON schema enforced by the runtime."""
        schema = {
            **deepcopy(self.constraints),
            "type": "object",
            "properties": deepcopy(self.parameters),
            "additionalProperties": False,
        }
        if self.required:
            schema["required"] = list(self.required)
        return _remove_empty_required(schema)

    def prompt_argument_schema(self) -> dict[str, Any]:
        """Return the compact JSON schema exposed to the model."""
        return _model_compatible_schema(self.runtime_argument_schema())

    def to_runtime_spec(self) -> dict[str, object]:
        spec: dict[str, object] = {
            "id": self.tool_name,
            "description": self.description,
            "binding": dict(self.binding),
            "argument_schema": self.runtime_argument_schema(),
            "prompt_argument_schema": self.prompt_argument_schema(),
        }
        if self.action_space_mode:
            spec["action_space_mode"] = self.action_space_mode
        return spec


def _validate_game_controls(game_controls: GameControls, action_space_mode: str) -> None:
    unsupported_keys = sorted(set(game_controls.keys) - set(STANDARD_KEYBOARD_KEYS))
    if unsupported_keys:
        raise ValueError(
            f"game_controls.keys contains values unsupported by action-space mode "
            f"{action_space_mode!r}: {unsupported_keys}"
        )

    for field_name in ("mouse_click", "mouse_hold"):
        unsupported_buttons = sorted(set(getattr(game_controls, field_name)) - set(STANDARD_MOUSE_BUTTONS))
        if unsupported_buttons:
            raise ValueError(
                f"game_controls.{field_name} contains values unsupported by action-space mode "
                f"{action_space_mode!r}: {unsupported_buttons}"
            )


def _wait_tool(duration_ms: int, action_space_mode: str) -> UnifiedActionToolSpec:
    return UnifiedActionToolSpec(
        tool_name="wait",
        action_space_mode=action_space_mode,
        description="wait for one game step.",
        binding=_game_step_action("wait", duration_ms),
    )


def _mouse_move_control_schema() -> dict[str, Any]:
    relative_limit = int(PLAYER1_CONTROL_RELATIVE_LIMIT)
    relative_schema = {
        "type": "object",
        "properties": {
            "mode": {"const": "relative"},
            "dx": {
                "type": "integer",
                "minimum": -relative_limit,
                "maximum": relative_limit,
                "description": "positive moves right; negative moves left.",
            },
            "dy": {
                "type": "integer",
                "minimum": -relative_limit,
                "maximum": relative_limit,
                "description": "positive moves down; negative moves up.",
            },
        },
        "required": ["mode", "dx", "dy"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "description": PLAYER1_CONTROL_RELATIVE_MOUSE_PROMPT,
        "oneOf": [
            relative_schema,
            {
                "type": "object",
                "properties": {
                    "mode": {"const": "absolute"},
                    "x": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 1000,
                        "description": "0 is the left edge and 1000 is the right edge of the visible game width.",
                    },
                    "y": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 1000,
                        "description": "0 is the top edge and 1000 is the bottom edge of the visible game height.",
                    },
                },
                "required": ["mode", "x", "y"],
                "additionalProperties": False,
            },
        ],
    }


def _control_keys_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(STANDARD_KEYBOARD_KEYS)},
        "minItems": 1,
        "uniqueItems": True,
        "description": "use the keys listed in Role and Controls.",
    }


def _split_control_mouse_tool(
    duration_ms: int,
    action_space_mode: str,
) -> UnifiedActionToolSpec:
    return UnifiedActionToolSpec(
        tool_name="mouse_control",
        action_space_mode=action_space_mode,
        description="control mouse input for one game step.",
        binding=_game_control_binding(action_space_mode, duration_ms),
        parameters={
            "mouse_move": _mouse_move_control_schema(),
            "mouse_click": {
                "type": "string",
                "enum": list(STANDARD_MOUSE_BUTTONS),
                "description": "one click after the optional mouse movement.",
            },
            "mouse_hold": {
                "type": "string",
                "enum": list(STANDARD_MOUSE_BUTTONS),
                "description": "one button held for the full game step; repeat it in consecutive game steps to continue holding.",
            },
            "mouse_scroll": {
                "type": "string",
                "enum": list(MOUSE_SCROLL_DIRECTIONS),
                "description": "one fixed vertical scroll step.",
            },
        },
        constraints={"minProperties": 1},
    )


def _split_control_key_tool(
    duration_ms: int,
    action_space_mode: str,
) -> UnifiedActionToolSpec:
    return UnifiedActionToolSpec(
        tool_name="key_control",
        action_space_mode=action_space_mode,
        description="control keyboard input for one game step.",
        binding=_game_control_binding(action_space_mode, duration_ms),
        parameters={
            "key_hold": {
                **_control_keys_schema(),
                "description": "keys held for the full game step; repeat them in consecutive game steps to continue holding.",
            },
            "key_tap": {
                **_control_keys_schema(),
                "description": "keys tapped once.",
            },
        },
        constraints={"minProperties": 1},
    )


def _split_control_tools(
    duration_ms: int,
    action_space_mode: str,
) -> list[UnifiedActionToolSpec]:
    tools_by_name = {
        "mouse_control": _split_control_mouse_tool(duration_ms, action_space_mode),
        "key_control": _split_control_key_tool(duration_ms, action_space_mode),
        "wait": _wait_tool(duration_ms, action_space_mode),
    }
    return [tools_by_name[name] for name in PLAYER1_CONTROL_MODEL_TOOL_ORDER]


def build_unified_action_space_tools(
    game_controls: GameControls,
    action_space_mode: str,
) -> list[UnifiedActionToolSpec]:
    """Return the shared Player-1 Control tools with the environment cadence."""

    action_space_mode = require_action_space_mode(action_space_mode)
    _validate_game_controls(game_controls, action_space_mode)
    duration_ms = _duration_ms(game_controls.duration_ms)
    return _split_control_tools(duration_ms, action_space_mode)


def build_game_control_role_controls(game_controls: GameControls) -> RoleControls:
    """Return runtime role controls from unified game controls."""

    duration_s = _duration_ms(game_controls.duration_ms) / 1000.0
    return RoleControls(
        allowed_keys=set(game_controls.allowed_keys),
        hold_duration=duration_s,
        key_durations={key: duration_s for key in game_controls.allowed_keys},
        allow_clicks=game_controls.allow_clicks,
    )


def build_unified_action_space_map(
    action_tools: Sequence[UnifiedActionToolSpec],
) -> dict[str, dict[str, Any]]:
    """Build the strict runtime action lookup keyed by tool name."""

    modes = {action.action_space_mode for action in action_tools}
    if len(modes) > 1:
        raise ValueError(f"Unified action tools cannot mix action-space modes: {sorted(modes)}")

    mapping: dict[str, dict[str, Any]] = {}
    for action in action_tools:
        if not action.tool_name or not action.binding:
            raise ValueError("Each unified action tool requires a name and runtime binding")
        if action.tool_name in mapping:
            raise ValueError(f"Duplicate unified action tool: {action.tool_name}")
        mapping[action.tool_name] = {
            **deepcopy(action.binding),
            "_action_space_mode": action.action_space_mode,
            "argument_schema": action.runtime_argument_schema(),
        }
    return mapping


def build_model_action_tools(runtime_tool_specs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build model-facing function definitions from compact prompt schemas."""

    tools: list[dict[str, Any]] = []
    for spec in runtime_tool_specs:
        tool_name = str(spec.get("id") or "").strip()
        prompt_schema = spec.get("prompt_argument_schema")
        if not tool_name or not isinstance(prompt_schema, Mapping):
            raise ValueError("Each runtime tool spec requires an id and prompt_argument_schema")
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": str(spec.get("description") or "").strip(),
                    "parameters": deepcopy(dict(prompt_schema)),
                },
            }
        )
    if not tools:
        raise ValueError("Native tool formatting requires at least one runtime tool spec")
    return tools
