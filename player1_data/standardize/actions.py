"""Strict Player-1 Control data-side validation and XML rendering."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from player1.agents.actions.control import (
    PLAYER1_CONTROL_CANONICAL_TOOL_ORDER,
    PLAYER1_CONTROL_KEY_ARGUMENTS,
    PLAYER1_CONTROL_KEY_TOOL,
    PLAYER1_CONTROL_MOUSE_ARGUMENTS,
    PLAYER1_CONTROL_MOUSE_TOOL,
    PLAYER1_CONTROL_WAIT_TOOL,
)
from player1.agents.actions.devices import (
    MOUSE_SCROLL_DIRECTIONS,
    STANDARD_KEYBOARD_KEYS,
    STANDARD_MOUSE_BUTTONS,
)
from player1.agents.actions.serialization import ACTION_FORMAT_QWEN3_CODER_XML, render_action_payload
from player1.datasets.player1_control import (
    ACTION_SPACE_MODE,
)
from player1.datasets.player1_control import (
    PLAYER1_CONTROL_ABSOLUTE_MAX as ABSOLUTE_MAX,
)
from player1.datasets.player1_control import (
    PLAYER1_CONTROL_ABSOLUTE_MIN as ABSOLUTE_MIN,
)
from player1.datasets.player1_control import (
    PLAYER1_CONTROL_DURATION_MS as DURATION_MS,
)
from player1.datasets.player1_control import (
    PLAYER1_CONTROL_RELATIVE_MAX as RELATIVE_MAX,
)
from player1.datasets.player1_control import (
    PLAYER1_CONTROL_RELATIVE_MIN as RELATIVE_MIN,
)

ACTION_FRAME_SCHEMA = "player1.action.frame"
DEVICE_COORDINATE_CONVENTION = "positive_x_right_positive_y_down"

ACTION_FORMAT = ACTION_FORMAT_QWEN3_CODER_XML
KEY_TOOL = PLAYER1_CONTROL_KEY_TOOL
MOUSE_TOOL = PLAYER1_CONTROL_MOUSE_TOOL
WAIT_TOOL = PLAYER1_CONTROL_WAIT_TOOL
KEY_ARGUMENTS = PLAYER1_CONTROL_KEY_ARGUMENTS
MOUSE_ARGUMENTS = PLAYER1_CONTROL_MOUSE_ARGUMENTS
TOOL_ORDER = PLAYER1_CONTROL_CANONICAL_TOOL_ORDER


def _integer_axis(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer in [{minimum},{maximum}]")
    return value


def _key_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty key list")
    if any(not isinstance(key, str) or key not in STANDARD_KEYBOARD_KEYS for key in value):
        raise ValueError(f"{field} contains an unsupported key")
    ordered = [key for key in STANDARD_KEYBOARD_KEYS if key in set(value)]
    if len(ordered) != len(value):
        raise ValueError(f"{field} must not contain duplicate keys")
    return ordered


def _mouse_move(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("mouse_move must be an object")
    mode = value.get("mode")
    if mode == "absolute":
        if set(value) != {"mode", "x", "y"}:
            raise ValueError("Player-1 Control absolute mouse_move must be exactly mode/x/y")
        return {
            "mode": mode,
            "x": _integer_axis(value.get("x"), field="mouse_move.x", minimum=ABSOLUTE_MIN, maximum=ABSOLUTE_MAX),
            "y": _integer_axis(value.get("y"), field="mouse_move.y", minimum=ABSOLUTE_MIN, maximum=ABSOLUTE_MAX),
        }
    if mode == "relative":
        if set(value) != {"mode", "dx", "dy"}:
            raise ValueError("Player-1 Control relative mouse_move must be exactly mode/dx/dy")
        canonical = {
            "mode": mode,
            "dx": _integer_axis(value.get("dx"), field="mouse_move.dx", minimum=RELATIVE_MIN, maximum=RELATIVE_MAX),
            "dy": _integer_axis(value.get("dy"), field="mouse_move.dy", minimum=RELATIVE_MIN, maximum=RELATIVE_MAX),
        }
        if canonical["dx"] == 0 and canonical["dy"] == 0:
            raise ValueError("Player-1 Control exact zero relative mouse_move must be omitted")
        return canonical
    raise ValueError("Player-1 Control mouse_move mode must be absolute or relative")


def validate_player1_control_frame(frame: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical Player-1 Control tool-call envelope for one neutral frame."""

    if not isinstance(frame, Mapping) or frame.get("schema_version") != ACTION_FRAME_SCHEMA:
        raise ValueError(f"action frame must use {ACTION_FRAME_SCHEMA}")
    if frame.get("coordinate_convention") != DEVICE_COORDINATE_CONVENTION:
        raise ValueError("action frame must use device coordinates")
    duration = frame.get("duration_ms")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration != DURATION_MS:
        raise ValueError(f"Player-1 Control requires duration_ms={DURATION_MS}")
    active = set(frame) - {"schema_version", "duration_ms", "coordinate_convention", "wait"}
    if frame.get("wait") is True:
        if active:
            raise ValueError("wait must be exclusive")
        return {
            "action_space_mode": ACTION_SPACE_MODE,
            "tool_calls": [{"tool_name": WAIT_TOOL, "arguments": {}}],
        }
    if frame.get("wait") is not None:
        raise ValueError("wait must be true when present")
    unknown = active - set(KEY_ARGUMENTS) - set(MOUSE_ARGUMENTS)
    if unknown:
        raise ValueError(f"action frame has unsupported fields: {sorted(unknown)}")

    key_arguments = {name: _key_list(frame[name], field=name) for name in KEY_ARGUMENTS if name in frame}
    if set(key_arguments.get("key_hold", [])) & set(key_arguments.get("key_tap", [])):
        raise ValueError("key_hold and key_tap must be disjoint")
    mouse_arguments: dict[str, Any] = {}
    if "mouse_move" in frame:
        mouse_arguments["mouse_move"] = _mouse_move(frame["mouse_move"])
    for name in ("mouse_click", "mouse_hold"):
        if name in frame:
            value = frame[name]
            if not isinstance(value, str) or value not in STANDARD_MOUSE_BUTTONS:
                raise ValueError(f"{name} contains an unsupported mouse button")
            mouse_arguments[name] = value
    if mouse_arguments.get("mouse_click") == mouse_arguments.get("mouse_hold") and "mouse_click" in mouse_arguments:
        raise ValueError("mouse_click and mouse_hold must be different")
    if "mouse_scroll" in frame:
        value = frame["mouse_scroll"]
        if value not in MOUSE_SCROLL_DIRECTIONS:
            raise ValueError("mouse_scroll must be up or down")
        mouse_arguments["mouse_scroll"] = value

    calls: dict[str, dict[str, Any]] = {}
    if key_arguments:
        calls[KEY_TOOL] = {"tool_name": KEY_TOOL, "arguments": key_arguments}
    if mouse_arguments:
        calls[MOUSE_TOOL] = {"tool_name": MOUSE_TOOL, "arguments": mouse_arguments}
    if not calls:
        raise ValueError("action frame has no action")
    return {
        "action_space_mode": ACTION_SPACE_MODE,
        "tool_calls": [calls[name] for name in TOOL_ORDER if name in calls],
    }


def render_player1_control_frame(frame: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Validate and render one Player-1 Control frame using flat-leaf XML."""

    canonical = validate_player1_control_frame(frame)
    orders = {KEY_TOOL: KEY_ARGUMENTS, MOUSE_TOOL: MOUSE_ARGUMENTS}
    rendered = "\n".join(
        render_action_payload(ACTION_FORMAT, call, argument_order=orders.get(call["tool_name"], ()))
        for call in canonical["tool_calls"]
    )
    return canonical, rendered


__all__ = [
    "ACTION_FORMAT",
    "KEY_TOOL",
    "MOUSE_TOOL",
    "WAIT_TOOL",
    "render_player1_control_frame",
    "validate_player1_control_frame",
]


def frame_action(arguments):
    frame = {
        "schema_version": ACTION_FRAME_SCHEMA,
        "coordinate_convention": DEVICE_COORDINATE_CONVENTION,
        "duration_ms": DURATION_MS,
        **arguments,
    }
    if not arguments:
        frame["wait"] = True
    _, action = render_player1_control_frame(frame)
    return frame, action
