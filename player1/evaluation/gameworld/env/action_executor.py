"""Translate structured agent commands into Playwright actions."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Iterable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from playwright.async_api import Page

if TYPE_CHECKING:
    from catalog.games._base import RoleControls

LOGGER = logging.getLogger(__name__)

DEFAULT_ACTION_DURATION = 0.1
DEFAULT_TYPE_DURATION = 0.5
MAX_ACTION_DURATION_SECONDS = 2.0
KEY_SPLIT_PATTERN = re.compile(r"[,+\s]+")
KEY_ALIASES = {
    "arrowleft": "ArrowLeft",
    "left": "ArrowLeft",
    "arrowright": "ArrowRight",
    "right": "ArrowRight",
    "arrowup": "ArrowUp",
    "up": "ArrowUp",
    "arrowdown": "ArrowDown",
    "down": "ArrowDown",
    "space": "Space",
    "spacebar": "Space",
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "shift": "Shift",
    "shiftleft": "Shift",
    "shiftright": "ShiftRight",
    "control": "Control",
    "ctrl": "Control",
    "controlleft": "Control",
    "controlright": "ControlRight",
    "alt": "Alt",
    "altleft": "Alt",
    "altright": "AltRight",
    "slash": "/",
    "period": ".",
    "comma": ",",
    "quote": "'",
    "apostrophe": "'",
    "semicolon": ";",
    "backslash": "\\",
    "bracketleft": "[",
    "bracketright": "]",
    "minus": "-",
    "equal": "=",
}

MOUSE_BUTTONS = {"left", "right", "middle"}
CANONICAL_ACTIONS = {
    "click",
    "click_hold",
    "mouse_move",
    "drag",
    "scroll",
    "type",
    "press_key",
    "press_keys",
    "wait",
}
ActionDict = dict[str, Any]


class ActionExecutor:
    """Executes normalized JSON-like commands on a Playwright page."""

    @staticmethod
    def normalize_action_batch(action: Any) -> list[dict[str, Any]]:
        """Accept exactly one primitive command for one model step."""
        if isinstance(action, dict):
            return [action]
        if isinstance(action, list) and len(action) == 1 and isinstance(action[0], dict):
            return [action[0]]
        return []

    def __init__(
        self,
        page: Page,
        controls: RoleControls | None,
    ):
        self.allow_any_key = controls is None
        self.page = page
        self.controls = controls or SimpleNamespace(
            allowed_keys=set(),
            hold_duration=DEFAULT_ACTION_DURATION,
            key_durations={},
            allow_clicks=True,
        )

        self.allowed_keys = self._normalize_key_set(self.controls.allowed_keys)
        self.allow_clicks = bool(self.controls.allow_clicks)
        self.hold_duration = self._coerce_duration(
            getattr(self.controls, "hold_duration", DEFAULT_ACTION_DURATION),
            default=DEFAULT_ACTION_DURATION,
        )
        self.key_durations = self._normalize_key_durations(self.controls.key_durations)

    def inspect_action(self, raw: Any) -> dict[str, Any]:
        """Return whether a low-level action payload is executable under current controls."""
        normalized = self._parse_action(raw)
        if normalized is not None:
            return {
                "is_valid": True,
                "reason": "valid",
                "invalid_kind": None,
                "normalized_action": normalized,
            }

        if not isinstance(raw, dict):
            return {
                "is_valid": False,
                "reason": "invalid_payload",
                "invalid_kind": "no_function_call",
                "normalized_action": None,
            }

        action_type = str(raw.get("action", "")).strip().lower()
        if not action_type:
            return {
                "is_valid": False,
                "reason": "missing_action",
                "invalid_kind": "no_function_call",
                "normalized_action": None,
            }

        mouse_actions = {
            "click",
            "click_hold",
            "drag",
            "scroll",
        }
        if action_type in mouse_actions and not self.allow_clicks:
            reason = "mouse_action_not_allowed"
        elif action_type in {"press_key", "press_keys"}:
            reason = "key_not_allowed_or_malformed"
        elif action_type not in CANONICAL_ACTIONS:
            reason = "unsupported_action_type"
        else:
            reason = "malformed_action_payload"

        return {
            "is_valid": False,
            "reason": reason,
            "invalid_kind": "out_of_space",
            "normalized_action": None,
        }

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _coerce_duration(value: Any, default: float) -> float:
        try:
            duration = float(default if value is None else value)
        except (TypeError, ValueError):
            duration = float(default)
        return min(MAX_ACTION_DURATION_SECONDS, max(0.0, duration))

    @staticmethod
    def _normalize_mouse_button(value: Any, default: str = "left") -> str | None:
        button = str(default if value is None else value).strip().lower()
        return button if button in MOUSE_BUTTONS else None

    def _normalize_key(self, key: str) -> str | None:
        """Normalize common key spellings to Playwright-compatible names."""
        if not isinstance(key, str) or not key.strip():
            return None

        normalized = str(key).strip()
        if len(normalized) == 1:
            normalized = normalized.lower()
        else:
            normalized = KEY_ALIASES.get(normalized.lower(), normalized)
        return normalized or None

    def _normalize_key_set(self, keys: Iterable[str] | None) -> set[str]:
        normalized: set[str] = set()
        for key in keys or ():
            normalized_key = self._normalize_key(key)
            if normalized_key:
                normalized.add(normalized_key)
        return normalized

    def _normalize_key_durations(self, key_durations: dict[str, Any] | None) -> dict[str, float]:
        normalized: dict[str, float] = {}
        if not isinstance(key_durations, dict):
            return normalized

        for key, duration in key_durations.items():
            normalized_key = self._normalize_key(key)
            if not normalized_key:
                continue
            normalized[normalized_key] = self._coerce_duration(duration, self.hold_duration)
        return normalized

    def _is_allowed_key(self, key: str) -> bool:
        return self.allow_any_key or key in self.allowed_keys

    def _coerce_allowed_key(self, key: str) -> str | None:
        """Normalize a key and ensure it is explicitly allowed."""
        normalized = self._normalize_key(key)
        if not normalized:
            return None
        if self._is_allowed_key(normalized):
            return normalized
        return None

    @staticmethod
    def _split_keys(raw_keys: str) -> list[str]:
        return [part for part in KEY_SPLIT_PATTERN.split(raw_keys.strip()) if part]

    @classmethod
    def _copy_action(cls, raw: dict[str, Any], action_type: str) -> ActionDict:
        action = dict(raw)
        action["action"] = action_type
        return action

    @classmethod
    def _numeric_fields(cls, raw: dict[str, Any], *names: str) -> dict[str, float] | None:
        values: dict[str, float] = {}
        for name in names:
            value = raw.get(name)
            if not cls._is_number(value):
                return None
            values[name] = float(value)
        return values

    def _parse_click_action(
        self,
        raw: dict[str, Any],
        *,
        action_type: str,
        forced_button: str | None = None,
    ) -> ActionDict | None:
        coords = self._numeric_fields(raw, "x", "y")
        if not coords or not self.allow_clicks:
            return None

        button = self._normalize_mouse_button(forced_button or raw.get("button"), default="left")
        if not button:
            return None

        action = self._copy_action(raw, action_type)
        action.update(coords)
        action["button"] = button
        if action_type == "click_hold":
            action["duration"] = self._coerce_duration(
                raw.get("duration"),
                self.hold_duration,
            )
        elif "duration" in raw:
            action["duration"] = self._coerce_duration(raw.get("duration"), self.hold_duration)
        return action

    def _parse_mouse_move(self, raw: dict[str, Any]) -> ActionDict | None:
        coords = self._numeric_fields(raw, "x", "y")
        if not coords:
            return None

        action = self._copy_action(raw, "mouse_move")
        action.update(coords)
        origin = self._numeric_fields(raw, "from_x", "from_y")
        if origin:
            action.update(origin)
        if "duration" in raw:
            action["duration"] = self._coerce_duration(raw.get("duration"), self.hold_duration)
        return action

    def _parse_drag(self, raw: dict[str, Any]) -> ActionDict | None:
        coords = self._numeric_fields(raw, "x1", "y1", "x2", "y2")
        if not coords or not self.allow_clicks:
            return None

        button = self._normalize_mouse_button(raw.get("button"), default="left")
        if not button:
            return None

        action = self._copy_action(raw, "drag")
        action.update(coords)
        action["button"] = button
        action["duration"] = self._coerce_duration(raw.get("duration"), self.hold_duration)
        steps = raw.get("steps")
        if steps is not None:
            try:
                action["steps"] = max(1, int(steps))
            except (TypeError, ValueError):
                return None
        return action

    def _parse_scroll(self, raw: dict[str, Any]) -> ActionDict | None:
        if not self.allow_clicks:
            return None

        delta_x = raw.get("delta_x", 0)
        delta_y = raw.get("delta_y", 0)
        if not self._is_number(delta_x) or not self._is_number(delta_y):
            return None

        action = self._copy_action(raw, "scroll")
        action["delta_x"] = float(delta_x)
        action["delta_y"] = float(delta_y)
        if "duration" in raw:
            action["duration"] = self._coerce_duration(raw.get("duration"), self.hold_duration)
        return action

    def _parse_type(self, raw: dict[str, Any]) -> ActionDict | None:
        text = raw.get("text")
        if text is None:
            return None
        text = str(text)
        if not text:
            return None

        normalized_characters: list[str] = []
        for character in text:
            if character in ("\n", "\r"):
                key = "Enter"
                normalized_character = "\n"
            elif character == "\b":
                key = "Backspace"
                normalized_character = character
            elif character == " ":
                key = "Space"
                normalized_character = character
            else:
                key = self._normalize_key(character)
                normalized_character = key
            if key is None or not self._is_allowed_key(key):
                return None
            normalized_characters.append(normalized_character)

        if raw.get("press_enter") and not self._is_allowed_key("Enter"):
            return None

        action = self._copy_action(raw, "type")
        action["text"] = "".join(normalized_characters)
        action["duration"] = self._coerce_duration(
            raw.get("duration"), DEFAULT_TYPE_DURATION
        )
        if "press_enter" in raw:
            action["press_enter"] = bool(raw.get("press_enter"))
        return action

    def _parse_press_key(self, raw: dict[str, Any]) -> ActionDict | None:
        key = raw.get("key")
        if not isinstance(key, str):
            return None

        key_parts = self._split_keys(key)
        if not key_parts:
            return None
        if len(key_parts) > 1:
            combo_action = self._copy_action(raw, "press_keys")
            combo_action["keys"] = key_parts
            combo_action.pop("key", None)
            return self._parse_press_keys(combo_action)

        normalized_key = self._coerce_allowed_key(key_parts[0])
        if not normalized_key:
            return None

        action = self._copy_action(raw, "press_key")
        action["key"] = normalized_key
        if "duration" in raw:
            action["duration"] = self._coerce_duration(raw.get("duration"), self.hold_duration)
        return action

    def _parse_press_keys(self, raw: dict[str, Any]) -> ActionDict | None:
        keys = raw.get("keys")
        if isinstance(keys, str):
            keys = self._split_keys(keys)
        if not isinstance(keys, (list, tuple)) or not keys:
            return None
        if len(keys) > 2:
            return None

        normalized_keys: list[str] = []
        for key in keys:
            normalized_key = self._coerce_allowed_key(str(key))
            if not normalized_key:
                return None
            normalized_keys.append(normalized_key)

        if len(set(normalized_keys)) != len(normalized_keys):
            return None
        normalized_key_set = set(normalized_keys)
        for opposite_pair in (
            {"ArrowLeft", "ArrowRight"},
            {"ArrowUp", "ArrowDown"},
            {"a", "d"},
            {"w", "s"},
        ):
            if opposite_pair <= normalized_key_set:
                return None

        action = self._copy_action(raw, "press_keys")
        action["keys"] = normalized_keys
        if "duration" in raw:
            action["duration"] = self._coerce_duration(raw.get("duration"), self.hold_duration)
        return action

    def _parse_wait(self, raw: dict[str, Any]) -> ActionDict:
        action = self._copy_action(raw, "wait")
        action["duration"] = self._coerce_duration(raw.get("duration"), self.hold_duration)
        return action

    def _parse_action(self, raw: dict[str, Any] | None) -> ActionDict | None:
        """Validate and normalize low-level actions before execution."""
        if not raw or not isinstance(raw, dict):
            return None

        action_type = str(raw.get("action", "")).strip().lower()
        if not action_type:
            return None

        parsers = {
            "click": lambda action: self._parse_click_action(action, action_type="click"),
            "click_hold": lambda action: self._parse_click_action(action, action_type="click_hold"),
            "mouse_move": self._parse_mouse_move,
            "drag": self._parse_drag,
            "scroll": self._parse_scroll,
            "type": self._parse_type,
            "press_key": self._parse_press_key,
            "press_keys": self._parse_press_keys,
            "wait": self._parse_wait,
        }
        parser = parsers.get(action_type)
        if not parser:
            return None
        return parser(raw)

    def _resolve_mouse_action_duration(self, action: ActionDict) -> float:
        return self._coerce_duration(action.get("duration"), self.hold_duration)

    def _resolve_key_hold_duration(self, action: ActionDict) -> float:
        explicit_duration = action.get("duration")
        if explicit_duration is not None:
            return self._coerce_duration(explicit_duration, self.hold_duration)

        action_type = action.get("action")
        if action_type == "press_key":
            key = action.get("key")
            if isinstance(key, str) and key in self.key_durations:
                return self.key_durations[key]
            return self.hold_duration

        if action_type == "press_keys":
            keys = action.get("keys")
            if isinstance(keys, list):
                key_overrides = [
                    self.key_durations[key]
                    for key in keys
                    if key in self.key_durations
                ]
                if key_overrides:
                    return max(key_overrides)
            return self.hold_duration

        return self.hold_duration

    def resolve_action_duration(self, action: ActionDict) -> float:
        """Return the configured gameplay window for a normalized action."""
        action_type = action.get("action")
        if action_type in {"press_key", "press_keys"}:
            return self._resolve_key_hold_duration(action)
        if action_type == "type":
            return self._coerce_duration(
                action.get("duration"), DEFAULT_TYPE_DURATION
            )
        return self._resolve_mouse_action_duration(action)

    async def _execute_click(self, action: ActionDict) -> None:
        button = action.get("button", "left")
        LOGGER.env("Executing Action: click(%s, %s) button=%s", action["x"], action["y"], button)
        await self.page.mouse.click(action["x"], action["y"], button=button)
        await asyncio.sleep(self._resolve_mouse_action_duration(action))

    async def _execute_click_hold(self, action: ActionDict) -> None:
        hold_seconds = self._resolve_mouse_action_duration(action)
        button = action.get("button", "left")
        LOGGER.env(
            "Executing Action: click_hold(%s, %s) button=%s hold=%.3f",
            action["x"],
            action["y"],
            button,
            hold_seconds,
        )
        await self.page.mouse.move(action["x"], action["y"])
        await self.page.mouse.down(button=button)
        await asyncio.sleep(hold_seconds)
        await self.page.mouse.up(button=button)

    async def _execute_type(self, action: ActionDict) -> None:
        duration = self._coerce_duration(
            action.get("duration"), DEFAULT_TYPE_DURATION
        )
        LOGGER.env(
            "Executing Action: keyboard type text(%s) duration=%.3f",
            action["text"],
            duration,
        )
        text = action["text"]
        press_enter = bool(action.get("press_enter"))

        stroke_count = len(text) + (1 if press_enter else 0)
        per_stroke_delay = (duration / stroke_count) if stroke_count > 0 else 0.0

        async def type_stroke(character: str) -> None:
            if character in ("\n", "\r"):
                await self.page.keyboard.press("Enter")
            elif character == "\b":
                await self.page.keyboard.press("Backspace")
            else:
                await self.page.keyboard.type(character)
            if per_stroke_delay > 0:
                await asyncio.sleep(per_stroke_delay)

        for character in text:
            await type_stroke(character)

        if press_enter:
            await type_stroke("\n")

    async def _execute_press_key(self, action: ActionDict) -> None:
        key = action.get("key", "")
        if not key:
            return

        hold_seconds = self._resolve_key_hold_duration(action)
        LOGGER.env("Executing Action: press_key key=%s hold=%.3f", key, hold_seconds)
        await self.page.keyboard.down(key)
        await asyncio.sleep(hold_seconds)
        await self.page.keyboard.up(key)

    async def _execute_press_keys(self, action: ActionDict) -> None:
        keys = action["keys"]
        hold_seconds = self._resolve_key_hold_duration(action)
        LOGGER.env("Executing Action: press_keys keys=%s hold=%.3f", keys, hold_seconds)

        for key in keys:
            await self.page.keyboard.down(key)
        await asyncio.sleep(hold_seconds)
        for key in reversed(keys):
            await self.page.keyboard.up(key)

    async def _execute_scroll(self, action: ActionDict) -> None:
        LOGGER.env("Executing Action: scroll(%s, %s)", action["delta_x"], action["delta_y"])
        await self.page.mouse.wheel(action["delta_x"], action["delta_y"])
        await asyncio.sleep(self._resolve_mouse_action_duration(action))

    async def _execute_mouse_move(self, action: ActionDict) -> None:
        LOGGER.env("Executing Action: mouse_move(%s, %s)", action["x"], action["y"])
        if "from_x" in action and "from_y" in action:
            await self.page.mouse.move(action["from_x"], action["from_y"])
        await self.page.mouse.move(action["x"], action["y"])
        await asyncio.sleep(self._resolve_mouse_action_duration(action))

    async def _execute_drag(self, action: ActionDict) -> None:
        button = action.get("button", "left")
        x1 = float(action["x1"])
        y1 = float(action["y1"])
        x2 = float(action["x2"])
        y2 = float(action["y2"])
        steps = max(1, int(action.get("steps", 10)))
        duration = self._coerce_duration(action.get("duration"), self.hold_duration)

        LOGGER.env(
            "Executing Action: drag(%s, %s) to (%s, %s) button=%s",
            x1,
            y1,
            x2,
            y2,
            button,
        )
        await self.page.mouse.move(x1, y1)
        await self.page.mouse.down(button=button)

        if duration > 0 and steps > 1:
            step_delay = duration / steps
            for step in range(1, steps + 1):
                next_x = x1 + (x2 - x1) * (step / steps)
                next_y = y1 + (y2 - y1) * (step / steps)
                await self.page.mouse.move(next_x, next_y)
                if step_delay > 0:
                    await asyncio.sleep(step_delay)
        else:
            await self.page.mouse.move(x2, y2, steps=steps)

        await self.page.mouse.up(button=button)

    async def _execute_wait(self, action: ActionDict) -> None:
        duration = self._coerce_duration(action.get("duration"), self.hold_duration)
        LOGGER.env("Executing Action: wait(%.3f)", duration)
        await asyncio.sleep(duration)

    async def execute(
        self,
        action: ActionDict,
        *,
        already_normalized: bool = False,
    ) -> dict[str, float | str] | None:
        """Execute a single action dictionary."""
        if not action:
            return None

        raw_action = dict(action)
        normalized_action = action if already_normalized else self._parse_action(action)
        if not normalized_action:
            LOGGER.warning(
                "Ignoring invalid/disallowed action payload: %s (allowed_keys=%s)",
                raw_action,
                sorted(self.allowed_keys) if self.allowed_keys else "ANY",
            )
            return None

        handlers = {
            "click": self._execute_click,
            "click_hold": self._execute_click_hold,
            "type": self._execute_type,
            "press_key": self._execute_press_key,
            "press_keys": self._execute_press_keys,
            "scroll": self._execute_scroll,
            "mouse_move": self._execute_mouse_move,
            "drag": self._execute_drag,
            "wait": self._execute_wait,
        }
        action_type = normalized_action["action"]
        handler = handlers.get(action_type)
        if not handler:
            LOGGER.env("Ignoring unsupported action type: %s", action_type)
            return None
        requested_duration_ms = self.resolve_action_duration(normalized_action) * 1_000
        started_at = time.perf_counter()
        await handler(normalized_action)
        return {
            "action_type": str(action_type),
            "requested_duration_ms": round(requested_duration_ms, 3),
            "action_wall_time_ms": round(
                (time.perf_counter() - started_at) * 1_000,
                3,
            ),
        }

    async def execute_actions(
        self,
        actions: Iterable[ActionDict],
        *,
        already_normalized: bool = False,
    ) -> list[dict[str, float | str]]:
        timings: list[dict[str, float | str]] = []
        for action in actions:
            timing = await self.execute(
                action,
                already_normalized=already_normalized,
            )
            if timing is not None:
                timings.append(timing)
        return timings
