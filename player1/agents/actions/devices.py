"""Keyboard and mouse device grammar for Player-1 Control."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

STANDARD_KEYBOARD_KEYS = (
    *tuple("abcdefghijklmnopqrstuvwxyz"),
    *tuple("0123456789"),
    "arrowup",
    "arrowdown",
    "arrowleft",
    "arrowright",
    "space",
    "enter",
    "escape",
    "tab",
    "backspace",
    "delete",
    "shift",
    "control",
    "alt",
)
STANDARD_MOUSE_BUTTONS = ("left", "right", "middle")
MOUSE_SCROLL_DIRECTIONS = ("up", "down")
MOUSE_SCROLL_STEP_PX = 200


def normalize_tool_call(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return one detached canonical tool call or reject malformed structure."""

    tool_name = raw.get("tool_name")
    arguments = raw.get("arguments")
    if not isinstance(tool_name, str) or not tool_name.strip() or not isinstance(arguments, Mapping):
        return None
    return {
        "tool_name": tool_name.strip(),
        "arguments": deepcopy(dict(arguments)),
    }


def resolve_mouse_scroll_delta(direction: str) -> tuple[int, int]:
    """Compile one symbolic scroll impulse into device pixel deltas."""

    if direction == "up":
        return 0, -MOUSE_SCROLL_STEP_PX
    if direction == "down":
        return 0, MOUSE_SCROLL_STEP_PX
    raise ValueError(f"Unsupported mouse_scroll direction: {direction!r}")


def conflicting_mouse_button_errors(
    arguments: Mapping[str, Any],
    *,
    path_prefix: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Reject click and hold for the same button in one atomic frame."""

    mouse_click = arguments.get("mouse_click")
    mouse_hold = arguments.get("mouse_hold")
    if not isinstance(mouse_click, str) or not mouse_click or mouse_click != mouse_hold:
        return []
    return [
        {
            "code": "conflicting_mouse_button",
            "path": [*path_prefix, "mouse_hold"],
            "message": "mouse_click and mouse_hold cannot use the same button in one control frame",
        }
    ]


__all__ = [
    "MOUSE_SCROLL_DIRECTIONS",
    "MOUSE_SCROLL_STEP_PX",
    "STANDARD_KEYBOARD_KEYS",
    "STANDARD_MOUSE_BUTTONS",
    "conflicting_mouse_button_errors",
    "normalize_tool_call",
    "resolve_mouse_scroll_delta",
]
