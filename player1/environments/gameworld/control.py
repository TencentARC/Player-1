"""Execute GameGym Control V0.5 frames inside GameWorld.

This adapter is intentionally self-contained in the vendored GameWorld tree.
It accepts the already parsed/validated runtime frame emitted by GameGym but
does not import any GameGym package. Keyboard, buttons, and 2D pointer input use
Playwright. Relative pointer input is normalized by the visible game width and
height, while each game remains responsible for its own camera sensitivity.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

_KEY_ALIASES = {
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "space": "Space",
    "enter": "Enter",
    "escape": "Escape",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "shift": "Shift",
    "control": "Control",
    "alt": "Alt",
}
_MOUSE_BUTTONS = frozenset(("left", "right", "middle"))
_DEFAULT_DURATION_S = 0.1
_MAX_DURATION_S = 2.0
_TAP_RELEASE_SETTLE_S = 0.025
_RELATIVE_POINTER_PROTOCOL = "normalized_viewport_delta_v1"
_RELATIVE_POINTER_NORMALIZED_RANGE = [-1000.0, 1000.0]
_POINTER_LOCK_STATE_SCRIPT = """
() => ({
    active: document.pointerLockElement !== null,
})
"""


def normalize_key(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        raise ValueError("Control V0.5 key cannot be empty")
    if len(key) == 1:
        return key.lower()
    return _KEY_ALIASES.get(key.lower(), key)


class GameGymControlExecutor:
    """Apply one atomic GameGym control frame through its supported device paths."""

    def __init__(self, page: Any, controls: Any):
        self.page = page
        self.controls = controls
        self.allowed_keys = {normalize_key(key) for key in controls.allowed_keys}
        self.allow_clicks = bool(controls.allow_clicks)
        self.hold_duration = self._coerce_duration(
            getattr(controls, "hold_duration", _DEFAULT_DURATION_S),
            default=_DEFAULT_DURATION_S,
        )
        raw_key_durations = getattr(controls, "key_durations", {})
        self.key_durations = {
            normalize_key(key): self._coerce_duration(duration, default=self.hold_duration)
            for key, duration in (raw_key_durations.items() if isinstance(raw_key_durations, Mapping) else ())
        }
        self._pointer: tuple[float, float] | None = None
        self._pointer_locked = False
        self._visible_geometry: dict[str, float] | None = None
        self._held_mouse_button: str | None = None

    @staticmethod
    def _coerce_duration(value: Any, *, default: float) -> float:
        try:
            duration = float(default if value is None else value)
        except (TypeError, ValueError):
            duration = float(default)
        return min(_MAX_DURATION_S, max(0.0, duration))

    def _frame_duration_s(
        self,
        *,
        held_keys: list[str],
        tapped_keys: list[str],
    ) -> float:
        key_overrides = [self.key_durations[key] for key in (*held_keys, *tapped_keys) if key in self.key_durations]
        if key_overrides:
            # Match GameWorld's native press_keys contract: when any key in a
            # simultaneous chord has an override, the longest override owns
            # the action duration. Otherwise the role-wide default wins.
            return max(key_overrides)
        return self.hold_duration

    def _keys(self, frame: Mapping[str, Any], field: str) -> list[str]:
        raw = frame.get(field, [])
        if raw is None:
            return []
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"Control V0.5 {field} must be a non-empty list when present")
        keys = [normalize_key(key) for key in raw]
        if len(keys) != len(set(keys)):
            raise ValueError(f"Control V0.5 {field} cannot contain duplicate keys")
        unsupported = sorted(set(keys) - self.allowed_keys)
        if unsupported:
            raise ValueError(f"Keys are not allowed by this GameWorld role: {unsupported}")
        return keys

    async def _release_keys(self, keys: list[str]) -> None:
        first_error: BaseException | None = None
        for key in reversed(keys):
            try:
                await self.page.keyboard.up(key)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    async def _execute_keyboard_frame(
        self,
        *,
        held_keys: list[str],
        tapped_keys: list[str],
        duration_s: float,
    ) -> None:
        active_keys: list[str] = []
        try:
            for key in held_keys:
                await self.page.keyboard.down(key)
                active_keys.append(key)

            if tapped_keys:
                tap_slot_s = duration_s / len(tapped_keys)
                # Frame-polled games must observe key-up before the same key is tapped again.
                release_duration_s = min(_TAP_RELEASE_SETTLE_S, tap_slot_s / 2.0)
                press_duration_s = tap_slot_s - release_duration_s
                for key in tapped_keys:
                    await self.page.keyboard.down(key)
                    active_keys.append(key)
                    try:
                        if press_duration_s > 0:
                            await asyncio.sleep(press_duration_s)
                    finally:
                        await self.page.keyboard.up(key)
                        active_keys.remove(key)
                    if release_duration_s > 0:
                        await asyncio.sleep(release_duration_s)
            elif duration_s > 0:
                await asyncio.sleep(duration_s)
        finally:
            await self._release_keys(active_keys)

    async def _visible_game_geometry(self) -> dict[str, float]:
        if self._visible_geometry is not None:
            return dict(self._visible_geometry)
        evaluate = getattr(self.page, "evaluate", None)
        if not callable(evaluate):
            viewport = getattr(self.page, "viewport_size", None)
            if not isinstance(viewport, Mapping):
                raise RuntimeError("Visible game geometry is unavailable")
            result: Any = {
                "left": 0.0,
                "top": 0.0,
                "width": viewport.get("width"),
                "height": viewport.get("height"),
            }
        else:
            result = await evaluate(
                """() => {
                    const api = window.gameGymAPI;
                    if (api && typeof api.getVisibleGameGeometry === "function") {
                        const geometry = api.getVisibleGameGeometry();
                        if (geometry && geometry.width > 0 && geometry.height > 0) return geometry;
                    }
                    const canvases = Array.from(document.querySelectorAll("canvas"));
                    const visible = canvases
                        .map(canvas => canvas.getBoundingClientRect())
                        .filter(rect => rect.width > 0 && rect.height > 0)
                        .sort((left, right) => right.width * right.height - left.width * left.height);
                    const rect = visible[0];
                    if (rect) return {left: rect.left, top: rect.top, width: rect.width, height: rect.height};
                    return {left: 0, top: 0, width: window.innerWidth, height: window.innerHeight};
                }"""
            )
        if not isinstance(result, Mapping):
            raise RuntimeError("Visible game geometry is unavailable")
        geometry = {
            "left": float(result.get("left", 0.0)),
            "top": float(result.get("top", 0.0)),
            "width": float(result.get("width", 0.0)),
            "height": float(result.get("height", 0.0)),
        }
        if geometry["width"] <= 0.0 or geometry["height"] <= 0.0:
            raise RuntimeError(f"Visible game geometry must be positive: {geometry!r}")
        self._visible_geometry = geometry
        return dict(geometry)

    async def validate_relative_pointer_contract(self) -> dict[str, Any]:
        geometry = await self._visible_game_geometry()
        return {
            "protocol": _RELATIVE_POINTER_PROTOCOL,
            "normalized_range": list(_RELATIVE_POINTER_NORMALIZED_RANGE),
            "visible_game_geometry": geometry,
        }

    async def _apply_relative_pointer_hook(self, raw: Mapping[str, Any]) -> bool:
        evaluate = getattr(self.page, "evaluate", None)
        if not callable(evaluate):
            return False
        result = await evaluate(
            """delta => {
                const api = window.gameGymAPI;
                if (!api || typeof api.applyRelativePointerInput !== "function") return false;
                api.applyRelativePointerInput(delta);
                return true;
            }""",
            {"dx": float(raw["dx"]), "dy": float(raw["dy"])},
        )
        return result is True

    async def _pointer_lock_active(self) -> bool:
        evaluate = getattr(self.page, "evaluate", None)
        if not callable(evaluate):
            return False
        result = await evaluate(_POINTER_LOCK_STATE_SCRIPT)
        if not isinstance(result, Mapping) or not isinstance(result.get("active"), bool):
            raise RuntimeError("Pointer-lock state probe returned an invalid result")
        return bool(result["active"])

    async def _move_pointer(self, raw: Any) -> None:
        if raw is None:
            return
        if not isinstance(raw, Mapping):
            raise ValueError("Control V0.5 mouse must be an object")
        mode = str(raw.get("mode") or "").strip().lower()
        if mode == "relative" and await self._apply_relative_pointer_hook(raw):
            return
        geometry = await self._visible_game_geometry()
        left, top = geometry["left"], geometry["top"]
        width, height = geometry["width"], geometry["height"]
        if mode == "absolute":
            self._pointer_locked = False
            x = left + float(raw["x"]) / 1000.0 * (width - 1.0)
            y = top + float(raw["y"]) / 1000.0 * (height - 1.0)
        elif mode == "relative":
            pointer_locked = await self._pointer_lock_active()
            if self._pointer_locked and not pointer_locked:
                # Pointer-lock release restores a browser-owned cursor
                # position. The unbounded trusted-input target used while
                # locked is no longer a valid free-cursor position.
                self._pointer = None
            self._pointer_locked = pointer_locked
            if self._pointer is None:
                if pointer_locked:
                    raise RuntimeError(
                        "Pointer-lock relative input requires a tracked trusted pointer origin "
                        "or gameGymAPI.applyRelativePointerInput"
                    )
                self._pointer = (left + width / 2.0, top + height / 2.0)
            x = self._pointer[0] + float(raw["dx"]) / 1000.0 * width
            y = self._pointer[1] + float(raw["dy"]) / 1000.0 * height
        else:
            raise ValueError(f"Unsupported Control V0.5 mouse mode: {mode!r}")
        if not self._pointer_locked:
            x = min(left + width - 1.0, max(left, x))
            y = min(top + height - 1.0, max(top, y))
        await self.page.mouse.move(x, y)
        self._pointer = (x, y)

    @staticmethod
    def _button(frame: Mapping[str, Any], field: str) -> str | None:
        raw = frame.get(field)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ValueError(f"Control V0.5 {field} must be an object")
        button = str(raw.get("button") or "").strip().lower()
        if button not in _MOUSE_BUTTONS:
            raise ValueError(f"Unsupported Control V0.5 mouse button: {button!r}")
        return button

    async def release_held_inputs(self) -> None:
        if self._held_mouse_button is not None:
            await self.page.mouse.up(button=self._held_mouse_button)
            self._held_mouse_button = None

    async def execute(self, frame: Mapping[str, Any]) -> dict[str, float | str]:
        try:
            if not isinstance(frame, Mapping):
                raise TypeError("Control V0.5 frame must be an object")
            action_type = str(frame.get("type") or frame.get("action") or "").strip()
            if action_type != "game_step_action":
                raise ValueError(f"Expected game_step_action, got {action_type!r}")

            held_keys = self._keys(frame, "key_hold") if "key_hold" in frame else []
            tapped_keys = self._keys(frame, "key_tap") if "key_tap" in frame else []
            overlap = sorted(set(held_keys) & set(tapped_keys))
            if overlap:
                raise ValueError(f"Control V0.5 key_hold/key_tap overlap: {overlap}")
            duration_s = self._frame_duration_s(held_keys=held_keys, tapped_keys=tapped_keys)
            started_at = time.perf_counter()

            click = self._button(frame, "mouse_click")
            hold = self._button(frame, "mouse_hold")
            if (click or hold or frame.get("scroll") is not None) and not self.allow_clicks:
                raise ValueError("Mouse buttons/scroll are disabled for this GameWorld role")
            if click and click == hold:
                raise ValueError("Control V0.5 cannot click and hold the same mouse button")

            if hold != self._held_mouse_button:
                await self.release_held_inputs()
            await self._move_pointer(frame.get("mouse"))
            if hold and self._held_mouse_button is None:
                # Track ownership before dispatch so a partially failed press is released.
                self._held_mouse_button = hold
                await self.page.mouse.down(button=hold)
            if click:
                if self._pointer is None:
                    geometry = await self._visible_game_geometry()
                    self._pointer = (
                        geometry["left"] + geometry["width"] / 2.0,
                        geometry["top"] + geometry["height"] / 2.0,
                    )
                    await self.page.mouse.move(*self._pointer)
                await self.page.mouse.click(*self._pointer, button=click)
            scroll = frame.get("scroll")
            if scroll is not None:
                if not isinstance(scroll, Mapping):
                    raise ValueError("Control V0.5 scroll must be an object")
                await self.page.mouse.wheel(float(scroll["dx"]), float(scroll["dy"]))
            await self._execute_keyboard_frame(
                held_keys=held_keys,
                tapped_keys=tapped_keys,
                duration_s=duration_s,
            )
        except BaseException as error:
            try:
                await self.release_held_inputs()
            except Exception as cleanup_error:
                error.add_note(f"GameWorld mouse release failed: {type(cleanup_error).__name__}: {cleanup_error}")
            raise
        return {
            "action_type": "game_step_action",
            "requested_duration_ms": round(duration_s * 1000.0, 3),
            "action_wall_time_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
        }


__all__ = ["GameGymControlExecutor", "normalize_key"]
