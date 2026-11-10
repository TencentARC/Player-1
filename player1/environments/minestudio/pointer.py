"""Resolution-independent pointer mapping for Minecraft GUI controls."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

NORMALIZED_POINTER_LIMIT = 1000.0
NORMALIZED_POINTER_PROTOCOL = "normalized_absolute_pointer_v1"
MINESTUDIO_POINTER_WIRE_OFFSET = 10_000.0


def _normalized_coordinate(value: float, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a finite number")
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{field} must be a finite number")
    if not 0.0 <= resolved <= NORMALIZED_POINTER_LIMIT:
        raise ValueError(f"{field} must be in [0, 1000]")
    return resolved


@dataclass(frozen=True)
class NormalizedPointerMapping:
    """Map top-left normalized GUI coordinates to the MineStudio input wire."""

    wire_offset: float = MINESTUDIO_POINTER_WIRE_OFFSET

    def __post_init__(self) -> None:
        if isinstance(self.wire_offset, bool) or not isinstance(self.wire_offset, (int, float)):
            raise TypeError("wire_offset must be a finite number")
        resolved = float(self.wire_offset)
        if not math.isfinite(resolved) or resolved <= NORMALIZED_POINTER_LIMIT:
            raise ValueError("wire_offset must be finite and greater than 1000")
        object.__setattr__(self, "wire_offset", resolved)

    def to_mine_studio_camera_wire(self, *, x: float, y: float) -> tuple[float, float]:
        """Return the private ``(camera[0], camera[1])`` absolute-pointer carrier."""

        normalized_x = _normalized_coordinate(x, field="mouse.x")
        normalized_y = _normalized_coordinate(y, field="mouse.y")
        return self.wire_offset + normalized_y, self.wire_offset + normalized_x

    def identity(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "protocol": NORMALIZED_POINTER_PROTOCOL,
            "normalized_range": [0, 1000],
            "origin": "top_left",
            "framebuffer_mapping": "coordinate / 1000 * (extent - 1)",
            "wire_carrier": "camera",
            "wire_offset": self.wire_offset,
        }
        return payload


DEFAULT_NORMALIZED_POINTER_MAPPING = NormalizedPointerMapping()


__all__ = [
    "DEFAULT_NORMALIZED_POINTER_MAPPING",
    "MINESTUDIO_POINTER_WIRE_OFFSET",
    "NORMALIZED_POINTER_LIMIT",
    "NORMALIZED_POINTER_PROTOCOL",
    "NormalizedPointerMapping",
]
