"""Compile validated Player-1-agent controls into MineStudio native actions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from player1.environments.minestudio.camera import (
    normalize_visible_game_size,
    resolve_relative_mouse,
)
from player1.environments.minestudio.input_semantics import (
    MINESTUDIO_ACTION_KEYS,
    MINESTUDIO_INPUT_BRIDGE_MARKER,
    MINESTUDIO_INPUT_BRIDGE_MARKER_CONTENT,
    MINESTUDIO_INPUT_HELD_VALUE,
    MINESTUDIO_INPUT_IMPULSE_VALUE,
    MINESTUDIO_KEYBOARD_INPUT_PROTOCOL,
    MLLM_GAME_AGENT_MINESTUDIO_INPUT_PROTOCOL,
    mine_studio_mouse_wheel_value,
    resolve_mine_studio_key_actions,
    verify_mine_studio_input_bridge,
)
from player1.environments.minestudio.pointer import (
    DEFAULT_NORMALIZED_POINTER_MAPPING,
    NormalizedPointerMapping,
)
from player1.environments.minestudio.timing import MINESTUDIO_STEP_DURATION_MS

_BUTTON_TO_MINESTUDIO_ACTION = MappingProxyType({"left": "attack", "right": "use"})
_CONTROL_FIELDS = frozenset(
    {
        "type",
        "id",
        "duration_ms",
        "key_hold",
        "key_tap",
        "mouse",
        "mouse_click",
        "mouse_hold",
        "scroll",
        "unified_action_tool",
    }
)
_WAIT_FIELDS = frozenset({"type", "id", "duration_ms", "unified_action_tool"})


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a finite number")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{field} must be a finite number")
    return resolved


def _structured_button(action: Mapping[str, Any], field: str) -> str | None:
    value = action.get(field)
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"button"}:
        raise TypeError(f"{field} must be a canonical button object")
    button = value.get("button")
    if not isinstance(button, str) or button not in _BUTTON_TO_MINESTUDIO_ACTION:
        raise ValueError(f"Unsupported MineStudio {field} button: {button!r}")
    return button


class MLLMGameAgentMineStudioInputManager:
    """Compile canonical Player-1 control frames into MineStudio input.

    Relative movement is resolved against the environment's explicit visible
    game size before entering MineStudio's private camera carrier.
    ``key_hold`` and ``key_tap`` explicitly compile to wire values 1 and 2. The patched Java
    engine consumes value 2 as one press/release impulse in the current step.
    """

    def __init__(
        self,
        *,
        visible_game_size: tuple[int, int],
        duration_ms: int = MINESTUDIO_STEP_DURATION_MS,
        pointer_mapping: NormalizedPointerMapping = DEFAULT_NORMALIZED_POINTER_MAPPING,
    ) -> None:
        if isinstance(duration_ms, bool) or duration_ms != MINESTUDIO_STEP_DURATION_MS:
            raise ValueError(f"MLLM MineStudio controls use the fixed {MINESTUDIO_STEP_DURATION_MS} ms tick")
        if not isinstance(pointer_mapping, NormalizedPointerMapping):
            raise TypeError("MineStudio pointer_mapping must be a NormalizedPointerMapping")
        self.visible_game_size = normalize_visible_game_size(visible_game_size)
        self.observation_size = self.visible_game_size
        self.camera_active = True
        self.duration_ms = MINESTUDIO_STEP_DURATION_MS
        self.pointer_mapping = pointer_mapping
        self._last_evidence: dict[str, Any] | None = None

    @property
    def protocol(self) -> str:
        return MLLM_GAME_AGENT_MINESTUDIO_INPUT_PROTOCOL

    @property
    def last_evidence(self) -> dict[str, Any] | None:
        return dict(self._last_evidence) if self._last_evidence is not None else None

    def reset(self) -> None:
        self._last_evidence = None
        self.observation_size = self.visible_game_size
        self.camera_active = True

    def bind_observation(self, size: tuple[int, int], *, gui_open: bool = False) -> None:
        """Bind the current policy image; GUI pointers keep native screen geometry."""
        self.observation_size = normalize_visible_game_size(size)
        self.camera_active = not gui_open

    def verify_runtime(self, engine_path: str | Path | None = None) -> Path:
        if engine_path is None:
            from minestudio.utils import get_mine_studio_dir

            engine_path = Path(get_mine_studio_dir()) / "engine" / "build" / "libs" / "mcprec-6.13.jar"
        return verify_mine_studio_input_bridge(engine_path)

    def compile_control(self, action: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(action, Mapping):
            raise TypeError("MLLM MineStudio control must be a mapping")
        unknown = sorted(str(field) for field in set(action) - _CONTROL_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported canonical MineStudio control fields: {unknown}")
        action_id = action.get("id")
        if action.get("type") != "game_step_action" or action_id not in {"control", "wait"}:
            raise ValueError("MLLM MineStudio input requires canonical game_step_action/control or wait")
        if action.get("unified_action_tool") not in {None, action_id}:
            raise ValueError(f"MLLM MineStudio input requires the unified {action_id} tool")
        duration = _finite_number(action.get("duration_ms"), field="duration_ms")
        if duration != self.duration_ms:
            raise ValueError(f"MLLM MineStudio controls must use one {self.duration_ms} ms tick")
        if action_id == "wait":
            payload_fields = sorted(str(field) for field in set(action) - _WAIT_FIELDS)
            if payload_fields:
                raise ValueError(f"wait cannot contain control payload fields: {payload_fields}")

        env_action: dict[str, Any] = {key: 0 for key in MINESTUDIO_ACTION_KEYS}
        env_action["camera"] = np.asarray([0.0, 0.0], dtype=np.float32)
        env_action["dwheel"] = np.asarray([0.0], dtype=np.float32)

        if action_id == "wait":
            self._last_evidence = {
                "protocol": self.protocol,
                "keyboard_protocol": MINESTUDIO_KEYBOARD_INPUT_PROTOCOL,
                "mouse_mode": None,
                "relative_mouse": None,
                "normalized_pointer": None,
                "held": [],
                "impulses": [],
                "camera": [0.0, 0.0],
                "dwheel": 0.0,
            }
            return env_action

        key_hold = action.get("key_hold")
        key_tap = action.get("key_tap")
        held_actions = resolve_mine_studio_key_actions(key_hold, field="key_hold") if key_hold is not None else ()
        tapped_actions = resolve_mine_studio_key_actions(key_tap, field="key_tap") if key_tap is not None else ()
        conflicting_actions = sorted(set(held_actions) & set(tapped_actions))
        if conflicting_actions:
            raise ValueError(f"key_hold and key_tap resolve to the same MineStudio actions: {conflicting_actions}")
        for action_name in held_actions:
            env_action[action_name] = MINESTUDIO_INPUT_HELD_VALUE
        for action_name in tapped_actions:
            env_action[action_name] = MINESTUDIO_INPUT_IMPULSE_VALUE

        mouse_mode: str | None = None
        relative_mouse: dict[str, Any] | None = None
        normalized_pointer: list[float] | None = None
        mouse = action.get("mouse")
        if mouse is not None:
            if not isinstance(mouse, Mapping):
                raise TypeError("mouse must be one canonical movement object")
            mouse_mode = str(mouse.get("mode") or "")
            if mouse_mode == "relative":
                if set(mouse) != {"mode", "dx", "dy"}:
                    raise TypeError("relative mouse must contain only mode, dx, and dy")
                dx = _finite_number(mouse.get("dx"), field="mouse.dx")
                dy = _finite_number(mouse.get("dy"), field="mouse.dy")
                resolved_mouse = resolve_relative_mouse(
                    dx=dx,
                    dy=dy,
                    visible_game_size=self.observation_size if self.camera_active else self.visible_game_size,
                    camera_active=self.camera_active,
                )
                env_action["camera"] = np.asarray(resolved_mouse.camera_wire, dtype=np.float32)
                relative_mouse = resolved_mouse.evidence()
            elif mouse_mode == "absolute":
                if set(mouse) != {"mode", "x", "y"}:
                    raise TypeError("absolute mouse must contain only mode, x, and y")
                camera_y, camera_x = self.pointer_mapping.to_mine_studio_camera_wire(
                    x=mouse.get("x"),
                    y=mouse.get("y"),
                )
                env_action["camera"] = np.asarray([camera_y, camera_x], dtype=np.float32)
                normalized_pointer = [
                    camera_x - self.pointer_mapping.wire_offset,
                    camera_y - self.pointer_mapping.wire_offset,
                ]
            else:
                raise ValueError(f"Unsupported MineStudio canonical mouse mode: {mouse_mode!r}")

        click = _structured_button(action, "mouse_click")
        hold = _structured_button(action, "mouse_hold")
        if click is not None and click == hold:
            raise ValueError("mouse_click and mouse_hold cannot use the same button")
        if hold is not None:
            env_action[_BUTTON_TO_MINESTUDIO_ACTION[hold]] = MINESTUDIO_INPUT_HELD_VALUE
        if click is not None:
            env_action[_BUTTON_TO_MINESTUDIO_ACTION[click]] = MINESTUDIO_INPUT_IMPULSE_VALUE

        wheel = mine_studio_mouse_wheel_value(action["scroll"]) if "scroll" in action else 0.0
        env_action["dwheel"] = np.asarray([wheel], dtype=np.float32)

        self._last_evidence = {
            "protocol": self.protocol,
            "keyboard_protocol": MINESTUDIO_KEYBOARD_INPUT_PROTOCOL,
            "mouse_mode": mouse_mode,
            "relative_mouse": relative_mouse,
            "normalized_pointer": normalized_pointer,
            "held": sorted(key for key in MINESTUDIO_ACTION_KEYS if env_action[key] == MINESTUDIO_INPUT_HELD_VALUE),
            "impulses": sorted(
                key for key in MINESTUDIO_ACTION_KEYS if env_action[key] == MINESTUDIO_INPUT_IMPULSE_VALUE
            ),
            "camera": env_action["camera"].tolist(),
            "dwheel": wheel,
        }
        return env_action


__all__ = [
    "MINESTUDIO_INPUT_BRIDGE_MARKER",
    "MINESTUDIO_INPUT_BRIDGE_MARKER_CONTENT",
    "MINESTUDIO_INPUT_HELD_VALUE",
    "MINESTUDIO_INPUT_IMPULSE_VALUE",
    "MLLM_GAME_AGENT_MINESTUDIO_INPUT_PROTOCOL",
    "MLLMGameAgentMineStudioInputManager",
]
