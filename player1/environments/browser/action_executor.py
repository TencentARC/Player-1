"""Execute canonical Player-1 actions with receipt-safe browser input ownership."""
from __future__ import annotations
import logging
import math
from typing import Any
from playwright.async_api import Page
from player1.runtime.camera import normalize_observation_size
from .contracts import validate_runtime_step_result

InputAction = dict[str, Any]
LOGGER = logging.getLogger(__name__)

MOUSE_BUTTONS = {"left", "right", "middle"}


MOUSE_MODE_RELATIVE = "relative"


MOUSE_MODE_ABSOLUTE = "absolute"


VISIBLE_GAME_GEOMETRY_PROTOCOL = "visible_game_geometry_v1"


VISIBLE_GAME_GEOMETRY_UNITS = "css_pixels"


HAS_PLAYER1_STEP_SCRIPT = "() => !!(window.gameGymAPI && typeof window.gameGymAPI.step === 'function')"


GET_VISIBLE_GAME_GEOMETRY_SCRIPT = """
() => {
    const api = window.gameGymAPI;
    if (!api || typeof api.getVisibleGameGeometry !== "function") {
        throw new Error("gameGymAPI.getVisibleGameGeometry unavailable");
    }
    return api.getVisibleGameGeometry();
}
"""


CALL_GAME_HOOK_SCRIPT = """
(name) => {
    try {
        if (typeof window[name] === "function") window[name]();
    } catch (_error) {
        // Input execution must still finalize if a game hook is unavailable.
    }
}
"""


PLAYER1_STEP_ACTION_SCRIPT = """
async ({ action, durationMs, pauseAround, observationSize }) => {
    const api = window.gameGymAPI;
    if (!api || typeof api.step !== "function") {
        return { ok: false, reason: "missing_player1_gym_step" };
    }

    const callHook = (name) => {
        try {
            if (typeof window[name] === "function") window[name]();
        } catch (_error) {
            // A broken pause hook should not prevent step finalization.
        }
    };

    const shouldPauseAround = Boolean(pauseAround);
    if (shouldPauseAround) callHook("__resumeGame");
    try {
        const result = await api.step(action || {}, {
            durationMs: Math.max(0, Number(durationMs) || 0),
            source: "agent",
            render: true,
            observationSize,
        });
        return { ok: true, result };
    } finally {
        if (shouldPauseAround) callHook("__pauseGame");
    }
}
"""


NATIVE_INPUT_WINDOW_SCRIPT = """
(operation) => {
    const api = window.gameGymAPI;
    if (!api) return false;
    if (operation === "begin") {
        if (typeof api.beginNativeInput !== "function" || typeof api.abortNativeInput !== "function") return false;
        api.beginNativeInput();
        return true;
    }
    if (typeof api.abortNativeInput !== "function") return false;
    api.abortNativeInput();
    return true;
}
"""



class InputActionExecutor:
    """Own native mouse state for one browser page."""

    def __init__(self, page: Page):
        self.page = page
        self._mouse_mode = MOUSE_MODE_RELATIVE
        self._held_mouse_buttons: set[str] = set()

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _validate_action(action: InputAction) -> None:
        if not isinstance(action, dict) or action.get("type") != "game_step_action":
            raise ValueError("Expected a validated Player-1 game_step_action")
        if not isinstance(action.get("id"), str) or not action["id"].strip():
            raise ValueError("Action id must be a non-empty string")
        duration = action.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 1 <= duration <= 10000:
            raise ValueError("Action duration_ms must be finite and between 1 and 10000")

    async def action_uses_virtual_time(self, action: InputAction) -> bool:
        self._validate_action(action)
        return bool(await self.page.evaluate(HAS_PLAYER1_STEP_SCRIPT))

    async def execute(self, action: InputAction, *, pause_around_virtual_time=False, observation_size=None):
        self._validate_action(action)
        return await self._execute_game_step_action(
            action, pause_around_virtual_time=pause_around_virtual_time, observation_size=observation_size,
        )

    async def _execute_game_step_action(
        self,
        action: InputAction,
        *,
        pause_around_virtual_time: bool = False,
        observation_size: tuple[int, int] | None = None,
    ) -> Any | None:
        duration_ms = max(0.0, float(action.get("duration_ms") or 0.0))
        if observation_size is not None:
            observation_size = normalize_observation_size(observation_size)
        payload_action = {k: v for k, v in action.items() if k not in {"type", "duration_ms", "unified_action_tool"}}
        mouse = payload_action.get("mouse")
        mouse_mode = str(mouse.get("mode") or "").strip().lower() if isinstance(mouse, dict) else ""
        action_id = str(payload_action.get("id") or "").strip()

        if action_id == "move_pointer" or mouse_mode == MOUSE_MODE_RELATIVE:
            self._mouse_mode = MOUSE_MODE_RELATIVE

        absolute_coords = self._absolute_mouse_coordinates(payload_action)
        if absolute_coords is not None:
            self._mouse_mode = MOUSE_MODE_ABSOLUTE

        browser_handles_pointer = self._mouse_mode == MOUSE_MODE_ABSOLUTE
        buttons = self._game_step_mouse_buttons(payload_action) if browser_handles_pointer else []
        requested_hold_buttons = set(self._game_step_mouse_hold_buttons(payload_action))
        # Keep an existing browser hold until release, including across a change
        # to relative pointer movement.
        held_buttons = (
            requested_hold_buttons
            if browser_handles_pointer
            else requested_hold_buttons & self._held_mouse_buttons
        )
        scroll_delta = self._game_step_scroll_delta(payload_action)
        uses_browser_pointer = (
            absolute_coords is not None
            or bool(buttons)
            or held_buttons != self._held_mouse_buttons
        )
        uses_browser_mouse = uses_browser_pointer or scroll_delta is not None
        manages_pause = bool(pause_around_virtual_time and uses_browser_mouse)
        native_input_window = False
        try:
            if uses_browser_mouse:
                native_input_window = bool(await self.page.evaluate(NATIVE_INPUT_WINDOW_SCRIPT, "begin"))
            if manages_pause:
                await self._call_game_hook("__resumeGame")
            await self._release_held_mouse_buttons_except(held_buttons)
            if absolute_coords is not None:
                await self._move_mouse_absolute(*absolute_coords)
            await self._press_held_mouse_buttons(held_buttons)

            for button in buttons:
                await self.page.mouse.down(button=button)
                await self.page.mouse.up(button=button)
            if scroll_delta is not None:
                await self.page.mouse.wheel(*scroll_delta)
            # Input ownership does not depend on whether this frame emitted a
            # new browser event: unchanged holds still belong to the browser.
            if browser_handles_pointer or held_buttons or scroll_delta is not None:
                payload_action = self._strip_browser_input_fields(
                    payload_action,
                    strip_pointer=browser_handles_pointer,
                    strip_hold=browser_handles_pointer or bool(held_buttons),
                    strip_scroll=scroll_delta is not None,
                )

            LOGGER.debug(
                "Executing Action: game_step_action id=%s duration_ms=%.1f player1_gym_step=%s",
                payload_action.get("id"),
                duration_ms,
                True,
            )
            result = await self.page.evaluate(
                PLAYER1_STEP_ACTION_SCRIPT,
                {
                    "action": payload_action,
                    "durationMs": duration_ms,
                    "pauseAround": bool(pause_around_virtual_time and not manages_pause),
                    "observationSize": observation_size,
                },
            )
            if isinstance(result, dict) and result.get("ok"):
                return validate_runtime_step_result(result.get("result"))
            raise RuntimeError(f"gameGymAPI.step action failed: {result}")
        except BaseException:
            await self.release_held_inputs()
            raise
        finally:
            try:
                if not pause_around_virtual_time:
                    await self.release_held_inputs()
            finally:
                try:
                    if native_input_window:
                        await self.page.evaluate(NATIVE_INPUT_WINDOW_SCRIPT, "abort")
                finally:
                    if manages_pause:
                        await self._call_game_hook("__pauseGame")

    @staticmethod
    def _absolute_mouse_coordinates(action: InputAction) -> tuple[float, float] | None:
        action_id = str(action.get("id") or "").strip()
        if action_id == "move_pointer_absolute":
            x = action.get("x")
            y = action.get("y")
        else:
            mouse = action.get("mouse")
            if not isinstance(mouse, dict) or str(mouse.get("mode") or "").strip().lower() != MOUSE_MODE_ABSOLUTE:
                return None
            x = mouse.get("x")
            y = mouse.get("y")
        if not InputActionExecutor._is_number(x) or not InputActionExecutor._is_number(y):
            return None
        return float(x), float(y)

    @staticmethod
    def _game_step_mouse_buttons(action: InputAction) -> list[str]:
        mouse_click = action.get("mouse_click")
        if isinstance(mouse_click, dict):
            button = str(mouse_click.get("button") or "").strip().lower()
            if button in MOUSE_BUTTONS:
                return [button]

        action_id = str(action.get("id") or "").strip()
        button = str(action.get("button") or "").strip().lower()
        if button in MOUSE_BUTTONS and action_id.startswith("mouse_"):
            return [button]
        if action_id == "mouse_left" or action.get("mouse_left") is True:
            return ["left"]
        if action_id == "mouse_right" or action.get("mouse_right") is True:
            return ["right"]
        return []

    @staticmethod
    def _game_step_mouse_hold_buttons(action: InputAction) -> list[str]:
        mouse_hold = action.get("mouse_hold")
        if not isinstance(mouse_hold, dict):
            return []
        button = str(mouse_hold.get("button") or "").strip().lower()
        return [button] if button in MOUSE_BUTTONS else []

    @staticmethod
    def _game_step_scroll_delta(action: InputAction) -> tuple[float, float] | None:
        scroll = action.get("scroll")
        if not isinstance(scroll, dict):
            return None
        dx = scroll.get("dx")
        dy = scroll.get("dy")
        if not InputActionExecutor._is_number(dx) or not InputActionExecutor._is_number(dy):
            return None
        return float(dx), float(dy)

    @staticmethod
    def _strip_browser_input_fields(
        action: InputAction,
        *,
        strip_pointer: bool,
        strip_hold: bool,
        strip_scroll: bool,
    ) -> InputAction:
        payload = dict(action)
        if strip_pointer:
            mouse = payload.get("mouse")
            if isinstance(mouse, dict) and str(mouse.get("mode") or "").strip().lower() == MOUSE_MODE_ABSOLUTE:
                payload.pop("mouse", None)
            for key in (
                "x",
                "y",
                "button",
                "mouse_click",
                "mouse_left",
                "mouse_right",
            ):
                payload.pop(key, None)
            if str(payload.get("id") or "").strip() in {
                "move_pointer_absolute",
                "mouse_left",
                "mouse_right",
            }:
                payload["id"] = "wait"
        if strip_hold:
            payload.pop("mouse_hold", None)
        if strip_scroll:
            payload.pop("scroll", None)
        return payload

    async def _move_mouse_absolute(self, x: float, y: float) -> None:
        if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1000 or not 0 <= y <= 1000:
            raise RuntimeError("absolute mouse action requires finite x/y in [0, 1000]")
        geometry = await self.page.evaluate(GET_VISIBLE_GAME_GEOMETRY_SCRIPT)
        if not isinstance(geometry, dict):
            raise RuntimeError("visible game geometry API must return an object")
        if (
            geometry.get("protocol") != VISIBLE_GAME_GEOMETRY_PROTOCOL
            or geometry.get("units") != VISIBLE_GAME_GEOMETRY_UNITS
        ):
            raise RuntimeError("gameGymAPI.getVisibleGameGeometry returned an unsupported geometry contract")
        try:
            left = float(geometry["left"])
            top = float(geometry["top"])
            width = float(geometry["width"])
            height = float(geometry["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("visible game geometry must contain finite left, top, width, and height") from exc
        if not all(math.isfinite(value) for value in (left, top, width, height)) or width <= 0 or height <= 0:
            raise RuntimeError("visible game geometry must contain finite positive dimensions")
        pixel_x = left + min(width - 1.0, max(0.0, x / 1000.0 * width))
        pixel_y = top + min(height - 1.0, max(0.0, y / 1000.0 * height))
        await self.page.mouse.move(pixel_x, pixel_y)

    async def _release_held_mouse_buttons_except(self, desired: set[str]) -> None:
        for button in sorted(self._held_mouse_buttons - desired):
            await self.page.mouse.up(button=button)
            self._held_mouse_buttons.remove(button)

    async def _press_held_mouse_buttons(self, desired: set[str]) -> None:
        for button in sorted(desired - self._held_mouse_buttons):
            await self.page.mouse.down(button=button)
            self._held_mouse_buttons.add(button)

    async def release_held_inputs(self) -> None:
        """Release browser mouse state retained across paused control frames."""

        for button in sorted(self._held_mouse_buttons):
            await self.page.mouse.up(button=button)
        self._held_mouse_buttons.clear()

    async def _call_game_hook(self, name: str) -> None:
        try:
            await self.page.evaluate(CALL_GAME_HOOK_SCRIPT, name)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Game hook %s failed during browser mouse input: %s", name, exc)
