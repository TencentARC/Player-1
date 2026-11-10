"""Shared runtime datatypes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ActionPayload = dict[str, Any] | None


@dataclass(slots=True)
class RoleControls:
    """Keyboard and mouse constraints for one player role."""

    allowed_keys: set[str] = field(default_factory=set)
    hold_duration: float = 0.2
    key_durations: dict[str, float] = field(default_factory=dict)
    allow_clicks: bool = True


@dataclass(slots=True)
class GameControls:
    """Unified keyboard and mouse controls exposed by a game."""

    duration_ms: int = 200
    keys: list[str] = field(default_factory=list)
    mouse_move: bool = False
    mouse_click: list[str] = field(default_factory=list)
    mouse_hold: list[str] = field(default_factory=list)

    @property
    def allowed_keys(self) -> set[str]:
        return {key for key in self.keys if key}

    @property
    def allow_clicks(self) -> bool:
        return bool(self.mouse_click or self.mouse_hold)


@dataclass
class Agent:
    """Runtime state for a game agent."""

    agent_id: str
    controls: RoleControls | None = None
    unified_action_space_map: dict[str, dict[str, Any]] | None = None
    step_index: int = 0
    eval_metrics: dict[str, Any] = field(default_factory=dict)


__all__ = ["ActionPayload", "Agent", "GameControls", "RoleControls"]
