"""Runtime game agent wrapper and related action types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agents.mm_agents.base.base_client import BaseClient
    from catalog.games._base import RoleControls

AgentType = Literal["general", "computer_use"]
ActionPayload = dict[str, Any] | list[dict[str, Any]] | None


@dataclass
class Agent:
    """Lightweight agent wrapper around a model client."""

    agent_id: str
    agent_type: AgentType
    client: BaseClient
    controls: RoleControls | None = None
    semantic_controls_map: dict[str, dict[str, Any]] | None = None
    step_index: int = 0
    eval_metrics: dict[str, Any] = field(default_factory=dict)


__all__ = ["ActionPayload", "Agent", "AgentType"]
