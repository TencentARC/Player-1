"""Player-1 Control relative-mouse mapping for MineStudio's camera carrier."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from player1.runtime.camera import CAMERA_DEGREES_PER_OBSERVATION_PIXEL
from player1.runtime.contracts import (
    MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT,
    MODEL_RELATIVE_POINTER_PROTOCOL,
)

NORMALIZED_RELATIVE_MOUSE_LIMIT = MODEL_RELATIVE_POINTER_NORMALIZED_LIMIT
NORMALIZED_RELATIVE_MOUSE_PROTOCOL = MODEL_RELATIVE_POINTER_PROTOCOL

# The pinned MineStudio input-v3 Java bridge expands each relative ``camera``
# carrier unit into this many mouse-movement pixels before dispatching the
# cursor callback. The Control contract remains normalized visible-game
# displacement; this constant only describes the existing private wire.
MINESTUDIO_CAMERA_WIRE_PIXELS_PER_UNIT = 6.666666666666667
# Pinned Minecraft client: mouseSensitivity=0.5, no smoothing; one callback
# pixel becomes 0.15 degrees. Compensate the private wire, not native policies.
MINESTUDIO_DEGREES_PER_MOUSE_PIXEL = 0.15


def normalize_visible_game_size(value: Sequence[int]) -> tuple[int, int]:
    """Validate the visible game dimensions used by the model action contract."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
        raise TypeError("visible_game_size must contain integer width and height")
    width, height = value
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
    ):
        raise TypeError("visible_game_size must contain integer width and height")
    if width <= 0 or height <= 0:
        raise ValueError("visible_game_size width and height must be positive")
    return width, height


def _normalized_delta(value: float, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a finite number")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{field} must be a finite number")
    if not -NORMALIZED_RELATIVE_MOUSE_LIMIT <= resolved <= NORMALIZED_RELATIVE_MOUSE_LIMIT:
        raise ValueError(f"{field} must be in [-1000, 1000]")
    return resolved


@dataclass(frozen=True)
class ResolvedRelativeMouse:
    """One Player-1 Control action resolved into visible-game pixels and MineStudio wire units."""

    normalized_dx: float
    normalized_dy: float
    visible_game_size: tuple[int, int]
    pixel_dx: float
    pixel_dy: float
    camera_wire_y: float
    camera_wire_x: float
    camera_active: bool

    @property
    def camera_wire(self) -> tuple[float, float]:
        """Return MineStudio's private ``camera[0], camera[1]`` carrier."""

        return self.camera_wire_y, self.camera_wire_x

    def evidence(self) -> dict[str, Any]:
        return {
            "protocol": NORMALIZED_RELATIVE_MOUSE_PROTOCOL,
            "normalized_delta": [self.normalized_dx, self.normalized_dy],
            "visible_game_size": list(self.visible_game_size),
            "pixel_delta": [self.pixel_dx, self.pixel_dy],
            "camera_wire": [self.camera_wire_y, self.camera_wire_x],
            "wire_pixels_per_unit": MINESTUDIO_CAMERA_WIRE_PIXELS_PER_UNIT,
            "camera_active": self.camera_active,
            "camera_degrees_per_observation_pixel": CAMERA_DEGREES_PER_OBSERVATION_PIXEL,
            "native_degrees_per_mouse_pixel": MINESTUDIO_DEGREES_PER_MOUSE_PIXEL,
        }


def resolve_relative_mouse(
    *,
    dx: float,
    dy: float,
    visible_game_size: Sequence[int],
    camera_active: bool = True,
) -> ResolvedRelativeMouse:
    """Use model image pixels for camera look; preserve native GUI displacement."""

    normalized_dx = _normalized_delta(dx, field="mouse.dx")
    normalized_dy = _normalized_delta(dy, field="mouse.dy")
    width, height = normalize_visible_game_size(visible_game_size)
    pixel_dx = normalized_dx / NORMALIZED_RELATIVE_MOUSE_LIMIT * width
    pixel_dy = normalized_dy / NORMALIZED_RELATIVE_MOUSE_LIMIT * height
    gain = CAMERA_DEGREES_PER_OBSERVATION_PIXEL / MINESTUDIO_DEGREES_PER_MOUSE_PIXEL if camera_active else 1.0
    return ResolvedRelativeMouse(
        normalized_dx=normalized_dx,
        normalized_dy=normalized_dy,
        visible_game_size=(width, height),
        pixel_dx=pixel_dx,
        pixel_dy=pixel_dy,
        camera_wire_y=pixel_dy * gain / MINESTUDIO_CAMERA_WIRE_PIXELS_PER_UNIT,
        camera_wire_x=pixel_dx * gain / MINESTUDIO_CAMERA_WIRE_PIXELS_PER_UNIT,
        camera_active=camera_active,
    )


__all__ = [
    "MINESTUDIO_CAMERA_WIRE_PIXELS_PER_UNIT",
    "NORMALIZED_RELATIVE_MOUSE_LIMIT",
    "NORMALIZED_RELATIVE_MOUSE_PROTOCOL",
    "ResolvedRelativeMouse",
    "normalize_visible_game_size",
    "resolve_relative_mouse",
]
