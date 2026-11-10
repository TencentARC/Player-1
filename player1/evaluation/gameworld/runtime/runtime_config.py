"""Runtime configuration for a full game session."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog.games._base import RoleControls


BENCHMARK_RELEASE = "fine-control-2026-08"


@dataclass
class RuntimeConfig:
    """Runtime configuration for the full game session."""

    # --- Game identity + environment ---
    url: str | None = None
    speed_multiplier: float = 1.0
    pause_during_inference: bool = True
    random_seed: int | None = None
    width: int = 1280
    height: int = 720

    # --- Task identity + evaluation ---
    task_id: str = ""
    game_id: str = ""
    game_url_suffix: str | None = None
    evaluator_config: dict[str, object] = field(default_factory=dict)
    benchmark_release: str = BENCHMARK_RELEASE
    max_steps: int = 400

    # --- Models & prompts ---
    model_ids: list[str] = field(default_factory=list)
    system_prompts: list[str] = field(default_factory=list)

    # --- Agent settings ---
    agent_count: int = 1
    enable_memory: list[bool] = field(default_factory=list)
    memory_rounds: int = 2
    memory_format: str = "vtvtvt"

    # --- Per-agent controls ---
    role_controls_maps: list[RoleControls] = field(default_factory=list)
    semantic_controls_maps: list[dict[str, dict[str, object]]] = field(
        default_factory=list
    )
    semantic_controls_specs: list[list[dict[str, object]]] = field(default_factory=list)

    # --- Others ---
    log_session_id: str = field(
        default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    log_root: str | None = None
