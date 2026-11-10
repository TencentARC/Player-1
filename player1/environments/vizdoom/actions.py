"""Map canonical Player-1 controls to ViZDoom actions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from player1.runtime.camera import normalize_observation_size
from player1.runtime.contracts import (
    MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT,
    MODEL_RELATIVE_POINTER_PROTOCOL,
)

from .suite import (
    MOUSE_SENSITIVITY_DEGREES_PER_PIXEL,
    RENDER_RESOLUTION,
    MapSpec,
    TURN_DELTA_DEGREES,
)


@dataclass(frozen=True)
class VizDoomAction:
    """Keyboard, mouse and weapon inputs executable by the native engine."""

    fire: bool = False
    move_forward: bool = False
    move_backward: bool = False
    strafe_left: bool = False
    strafe_right: bool = False
    speed: bool = False
    turn_left: bool = False
    turn_right: bool = False
    turn_delta: float = 0.0
    selected_weapon: int | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.turn_delta):
            raise ValueError("ViZDoom turn_delta must be finite")
        if self.selected_weapon is not None and self.selected_weapon not in range(1, 7):
            raise ValueError("ViZDoom selected_weapon must be in [1, 6] or None")

    def to_dict(self) -> dict[str, bool | float | int | None]:
        return asdict(self)

    def has_effect(self) -> bool:
        """Return whether this action changes combat or player state."""

        return bool(
            self.fire
            or self.move_forward
            or self.move_backward
            or self.strafe_left
            or self.strafe_right
            or self.turn_left
            or self.turn_right
            or self.turn_delta
            or self.selected_weapon is not None
        )


@dataclass(frozen=True)
class ActionMappingResult:
    action: VizDoomAction
    valid: bool
    invalid_reason: str | None
    evidence: dict[str, Any]


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _validate_turn_limit(max_turn_degrees: float | None) -> float | None:
    if max_turn_degrees is None:
        return None
    if (
        isinstance(max_turn_degrees, bool)
        or not isinstance(max_turn_degrees, (int, float))
        or not math.isfinite(float(max_turn_degrees))
        or float(max_turn_degrees) <= 0.0
    ):
        raise ValueError("ViZDoom max_turn_degrees must be a positive finite number or None")
    return float(max_turn_degrees)


def _apply_turn_limit(degrees: float, max_turn_degrees: float | None) -> float:
    limit = _validate_turn_limit(max_turn_degrees)
    if limit is None:
        return degrees
    return max(-limit, min(limit, degrees))


def _turn_delta_from_degrees(degrees: float, max_turn_degrees: float | None) -> float:
    return _apply_turn_limit(degrees, max_turn_degrees) / TURN_DELTA_DEGREES


def _canonical_mapping(
    raw: Mapping[str, Any],
    spec: MapSpec,
    *,
    max_turn_degrees: float | None,
    observation_size: tuple[int, int],
) -> ActionMappingResult:
    action_id = raw.get("id")
    if action_id == "wait":
        return ActionMappingResult(VizDoomAction(), True, None, {"source_format": "player1_control", "wait": True})
    if action_id != "control" or raw.get("type") != "game_step_action":
        return ActionMappingResult(
            VizDoomAction(),
            False,
            "unsupported_game_step_action",
            {"source_format": "player1_control", "action_id": action_id},
        )

    keys: set[str] = set()
    for field in ("key_hold", "key_tap"):
        values = raw.get(field, [])
        if values is None:
            continue
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            return ActionMappingResult(
                VizDoomAction(),
                False,
                f"invalid_{field}",
                {"source_format": "player1_control"},
            )
        keys.update(value.lower() for value in values)

    supported_keys = set(spec.allowed_keys)
    unsupported = sorted(keys - supported_keys)
    if unsupported:
        return ActionMappingResult(
            VizDoomAction(),
            False,
            f"unsupported_keys:{','.join(unsupported)}",
            {"source_format": "player1_control", "keys": sorted(keys)},
        )

    mouse = raw.get("mouse")
    normalized_dx = 0.0
    normalized_dy = 0.0
    pixel_dx = 0.0
    pixel_dy = 0.0
    resolved_yaw_degrees = 0.0
    if mouse is not None:
        if not isinstance(mouse, Mapping) or mouse.get("mode") != "relative":
            return ActionMappingResult(
                VizDoomAction(),
                False,
                "relative_mouse_required",
                {"source_format": "player1_control", "mouse": dict(mouse) if isinstance(mouse, Mapping) else mouse},
            )
        normalized_dx = _finite_number(mouse.get("dx"), field="mouse.dx")
        normalized_dy = _finite_number(mouse.get("dy"), field="mouse.dy")
        if normalized_dy != 0.0:
            return ActionMappingResult(
                VizDoomAction(),
                False,
                "vertical_mouse_unsupported",
                {"source_format": "player1_control", "mouse_dy": normalized_dy},
            )
        pixel_dx = normalized_dx / MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT * observation_size[0]
        pixel_dy = normalized_dy / MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT * observation_size[1]
        resolved_yaw_degrees = pixel_dx * MOUSE_SENSITIVITY_DEGREES_PER_PIXEL
        if resolved_yaw_degrees and spec.mouse_turn == "none":
            return ActionMappingResult(
                VizDoomAction(),
                False,
                "mouse_turn_unsupported",
                {"source_format": "player1_control", "map_id": spec.map_id},
            )
    applied_yaw_degrees = _apply_turn_limit(resolved_yaw_degrees, max_turn_degrees)

    click = raw.get("mouse_click")
    hold = raw.get("mouse_hold")
    fire = (
        isinstance(click, Mapping)
        and click.get("button") == "left"
        or isinstance(hold, Mapping)
        and hold.get("button") == "left"
    )
    if fire and not spec.fire:
        return ActionMappingResult(
            VizDoomAction(),
            False,
            "fire_unsupported",
            {"source_format": "player1_control", "map_id": spec.map_id},
        )

    weapon_keys = sorted(key for key in keys if key in {"1", "2", "3", "4", "5", "6"})
    if len(weapon_keys) > 1:
        return ActionMappingResult(
            VizDoomAction(),
            False,
            "conflicting_weapon_selection",
            {"source_format": "player1_control", "keys": sorted(keys)},
        )

    action_values: dict[str, bool | float] = {field: False for _, field in spec.key_actions}
    for key, field in spec.key_actions:
        if key in keys:
            action_values[field] = True
    if spec.mouse_turn == "buttons":
        action_values["turn_left"] = bool(action_values.get("turn_left")) or resolved_yaw_degrees < 0.0
        action_values["turn_right"] = bool(action_values.get("turn_right")) or resolved_yaw_degrees > 0.0
    action = VizDoomAction(
        fire=fire,
        **action_values,
        turn_delta=(
            _turn_delta_from_degrees(resolved_yaw_degrees, max_turn_degrees) if spec.mouse_turn == "delta" else 0.0
        ),
        selected_weapon=int(weapon_keys[0]) if weapon_keys else None,
    )
    if action.move_forward and action.move_backward:
        return ActionMappingResult(
            VizDoomAction(),
            False,
            "conflicting_forward_backward",
            {"source_format": "player1_control", "keys": sorted(keys)},
        )
    if (action.strafe_left and action.strafe_right) or (action.turn_left and action.turn_right):
        return ActionMappingResult(
            VizDoomAction(),
            False,
            "conflicting_left_right",
            {"source_format": "player1_control", "keys": sorted(keys)},
        )
    if not action.has_effect():
        return ActionMappingResult(
            VizDoomAction(),
            False,
            "control_has_no_effect",
            {
                "source_format": "player1_control",
                "keys": sorted(keys),
                "map_action_mode": spec.action_mode,
                "map_id": spec.map_id,
            },
        )
    return ActionMappingResult(
        action,
        True,
        None,
        {
            "source_format": "player1_control",
            "keys": sorted(keys),
            "relative_pointer_protocol": MODEL_RELATIVE_POINTER_PROTOCOL,
            "normalized_dx": normalized_dx,
            "normalized_dy": normalized_dy,
            "observation_size": list(observation_size),
            "pixel_dx": pixel_dx,
            "pixel_dy": pixel_dy,
            "mouse_sensitivity_degrees_per_pixel": MOUSE_SENSITIVITY_DEGREES_PER_PIXEL,
            "resolved_yaw_degrees": resolved_yaw_degrees,
            "applied_yaw_degrees": applied_yaw_degrees,
            "max_turn_degrees": max_turn_degrees,
            "map_action_mode": spec.action_mode,
            "map_id": spec.map_id,
        },
    )


def map_policy_action(
    raw: Mapping[str, Any],
    spec: MapSpec,
    *,
    max_turn_degrees: float | None = None,
    observation_size: tuple[int, int] = RENDER_RESOLUTION,
) -> ActionMappingResult:
    """Translate one canonical Player-1 action using the selected map controls."""

    _validate_turn_limit(max_turn_degrees)
    if not isinstance(raw, Mapping):
        return ActionMappingResult(VizDoomAction(), False, "action_not_mapping", {"source_type": type(raw).__name__})
    if raw.get("type") == "game_step_action":
        try:
            return _canonical_mapping(
                raw,
                spec,
                max_turn_degrees=max_turn_degrees,
                observation_size=normalize_observation_size(observation_size),
            )
        except (TypeError, ValueError) as exc:
            return ActionMappingResult(
                VizDoomAction(),
                False,
                "invalid_player1_control_values",
                {"source_format": "player1_control", "error": str(exc)},
            )
    return ActionMappingResult(VizDoomAction(), False, "action_type_not_supported", {"type": raw.get("type")})


__all__ = ["ActionMappingResult", "VizDoomAction", "map_policy_action"]
