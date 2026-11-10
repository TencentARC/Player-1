"""Structural contract for flat-wire split-device Player-1 Control frames."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from player1.runtime.contracts import (
    MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT,
    MODEL_RELATIVE_POINTER_PROTOCOL,
)

from .devices import (
    conflicting_mouse_button_errors,
    normalize_tool_call,
    resolve_mouse_scroll_delta,
)

ACTION_SPACE_MODE = "player1_control"


def is_control_action_space_mode(action_space_mode: str) -> bool:
    """Return whether the mode selects the Player-1 Control protocol."""

    return str(action_space_mode or "").strip() == ACTION_SPACE_MODE


def require_action_space_mode(action_space_mode: str) -> str:
    """Require the canonical Player-1 Control mode."""

    if not is_control_action_space_mode(action_space_mode):
        raise ValueError(f"Unsupported action_space_mode {action_space_mode!r}; expected {ACTION_SPACE_MODE}")
    return ACTION_SPACE_MODE


PLAYER1_CONTROL_KEY_TOOL = "key_control"
PLAYER1_CONTROL_MOUSE_TOOL = "mouse_control"
PLAYER1_CONTROL_WAIT_TOOL = "wait"

PLAYER1_CONTROL_RELATIVE_LIMIT = MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT
PLAYER1_CONTROL_RELATIVE_PROTOCOL = MODEL_RELATIVE_POINTER_PROTOCOL
PLAYER1_CONTROL_RELATIVE_MOUSE_PROMPT = """Move the pointer or camera with dx and dy in [-1000, 1000]

dx=1000 represents one full visible game
width,
and dy=1000 represents one full visible game height.

Positive dx moves right,
negative dx moves left,
positive dy moves down,
and negative dy moves up.

dx and dy set the mouse movement amount."""

PLAYER1_CONTROL_KEY_ARGUMENTS = ("key_hold", "key_tap")
PLAYER1_CONTROL_MOUSE_ARGUMENTS = (
    "mouse_move",
    "mouse_click",
    "mouse_hold",
    "mouse_scroll",
)

# The model schema and canonical history both put the higher-entropy mouse
# channel before keyboard. Semantically equivalent source orders still collapse
# to this one stable representation. The contract serializes mouse_move as one
# JSON leaf.
PLAYER1_CONTROL_MODEL_TOOL_ORDER = (
    PLAYER1_CONTROL_MOUSE_TOOL,
    PLAYER1_CONTROL_KEY_TOOL,
    PLAYER1_CONTROL_WAIT_TOOL,
)
PLAYER1_CONTROL_CANONICAL_TOOL_ORDER = (
    PLAYER1_CONTROL_MOUSE_TOOL,
    PLAYER1_CONTROL_KEY_TOOL,
)


def normalize_player1_control_frame(
    raw_tool_calls: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Return one canonical Player-1 Control frame after validating its call grammar."""

    if not 1 <= len(raw_tool_calls) <= 2:
        return None
    tool_calls = [normalize_tool_call(raw) for raw in raw_tool_calls]
    if any(call is None for call in tool_calls):
        return None
    normalized_calls = [call for call in tool_calls if call is not None]

    names = [call["tool_name"] for call in normalized_calls]
    if names == [PLAYER1_CONTROL_WAIT_TOOL]:
        if normalized_calls[0]["arguments"]:
            return None
        return {
            "action_space_mode": ACTION_SPACE_MODE,
            "tool_calls": normalized_calls,
        }
    if PLAYER1_CONTROL_WAIT_TOOL in names or len(set(names)) != len(names):
        return None
    if not set(names) <= set(PLAYER1_CONTROL_CANONICAL_TOOL_ORDER):
        return None

    allowed_arguments = {
        PLAYER1_CONTROL_KEY_TOOL: frozenset(PLAYER1_CONTROL_KEY_ARGUMENTS),
        PLAYER1_CONTROL_MOUSE_TOOL: frozenset(PLAYER1_CONTROL_MOUSE_ARGUMENTS),
    }
    by_name: dict[str, dict[str, Any]] = {}
    for call in normalized_calls:
        arguments = call["arguments"]
        if not arguments or not arguments.keys() <= allowed_arguments[call["tool_name"]]:
            return None
        by_name[call["tool_name"]] = call

    return {
        "action_space_mode": ACTION_SPACE_MODE,
        "tool_calls": [by_name[name] for name in PLAYER1_CONTROL_CANONICAL_TOOL_ORDER if name in by_name],
    }


def player1_control_tool_calls(frame: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Return canonical public tool calls from a validated-looking envelope."""

    if frame.get("action_space_mode") != ACTION_SPACE_MODE:
        return None
    raw_tool_calls = frame.get("tool_calls")
    if not isinstance(raw_tool_calls, list) or not all(isinstance(call, Mapping) for call in raw_tool_calls):
        return None
    normalized = normalize_player1_control_frame(raw_tool_calls)
    if normalized is None:
        return None
    return normalized["tool_calls"]


def validate_cross_arguments(
    arguments_by_tool: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate conflicts spanning the two independently parsed channels."""

    errors: list[dict[str, Any]] = []
    key_arguments = arguments_by_tool.get(PLAYER1_CONTROL_KEY_TOOL, {})
    conflicting_keys = sorted(set(key_arguments.get("key_hold") or []) & set(key_arguments.get("key_tap") or []))
    if conflicting_keys:
        errors.append(
            {
                "code": "conflicting_key",
                "path": [PLAYER1_CONTROL_KEY_TOOL, "key_tap"],
                "message": f"key_hold and key_tap cannot contain the same key: {conflicting_keys}",
            }
        )

    errors.extend(
        conflicting_mouse_button_errors(
            arguments_by_tool.get(PLAYER1_CONTROL_MOUSE_TOOL, {}),
            path_prefix=(PLAYER1_CONTROL_MOUSE_TOOL,),
        )
    )
    return errors


def compile_frame(
    arguments_by_tool: Mapping[str, Mapping[str, Any]],
    *,
    duration_ms: int,
) -> tuple[str, dict[str, Any]]:
    """Compile one fully validated Player-1 Control frame into one runtime action."""

    if PLAYER1_CONTROL_WAIT_TOOL in arguments_by_tool:
        return PLAYER1_CONTROL_WAIT_TOOL, {
            "type": "game_step_action",
            "id": PLAYER1_CONTROL_WAIT_TOOL,
            "duration_ms": duration_ms,
            "unified_action_tool": PLAYER1_CONTROL_WAIT_TOOL,
        }

    action: dict[str, Any] = {
        "type": "game_step_action",
        "id": "control",
        "duration_ms": duration_ms,
    }

    key_arguments = arguments_by_tool.get(PLAYER1_CONTROL_KEY_TOOL, {})
    for key in PLAYER1_CONTROL_KEY_ARGUMENTS:
        values = key_arguments.get(key)
        if isinstance(values, list) and values:
            action[key] = list(values)

    mouse_arguments = arguments_by_tool.get(PLAYER1_CONTROL_MOUSE_TOOL, {})
    mouse_move = mouse_arguments.get("mouse_move")
    if isinstance(mouse_move, Mapping):
        action["mouse"] = dict(mouse_move)

    mouse_click = mouse_arguments.get("mouse_click")
    if isinstance(mouse_click, str) and mouse_click:
        action["mouse_click"] = {"button": mouse_click}

    mouse_hold = mouse_arguments.get("mouse_hold")
    if isinstance(mouse_hold, str) and mouse_hold:
        action["mouse_hold"] = {"button": mouse_hold}

    mouse_scroll = mouse_arguments.get("mouse_scroll")
    if isinstance(mouse_scroll, str):
        dx, dy = resolve_mouse_scroll_delta(mouse_scroll)
        action["scroll"] = {"dx": dx, "dy": dy}

    action["unified_action_tool"] = "control"
    return "control", action


__all__ = [
    "ACTION_SPACE_MODE",
    "PLAYER1_CONTROL_CANONICAL_TOOL_ORDER",
    "PLAYER1_CONTROL_KEY_ARGUMENTS",
    "PLAYER1_CONTROL_KEY_TOOL",
    "PLAYER1_CONTROL_MODEL_TOOL_ORDER",
    "PLAYER1_CONTROL_MOUSE_ARGUMENTS",
    "PLAYER1_CONTROL_MOUSE_TOOL",
    "PLAYER1_CONTROL_RELATIVE_LIMIT",
    "PLAYER1_CONTROL_RELATIVE_MOUSE_PROMPT",
    "PLAYER1_CONTROL_RELATIVE_PROTOCOL",
    "PLAYER1_CONTROL_WAIT_TOOL",
    "compile_frame",
    "is_control_action_space_mode",
    "player1_control_tool_calls",
    "normalize_player1_control_frame",
    "require_action_space_mode",
    "validate_cross_arguments",
]
