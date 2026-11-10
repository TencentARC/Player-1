"""Runtime configuration for a full game session."""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import RoleControls


DEFAULT_GAME_WIDTH = 854
DEFAULT_GAME_HEIGHT = 480


@dataclass
class RuntimeConfig:
    """Runtime configuration for the full game session."""

    # --- Game identity + environment ---
    game_name: str = "game"
    pause_during_inference: bool = True
    random_seed: int | None = None
    game_api_options: dict[str, object] = field(default_factory=dict)
    width: int = DEFAULT_GAME_WIDTH
    height: int = DEFAULT_GAME_HEIGHT

    # --- Task identity + evaluation ---
    task_id: str = ""
    game_id: str = ""
    game_url_suffix: str | None = None
    evaluator_id: str = "noop"
    evaluator_config: dict[str, object] = field(default_factory=dict)
    training_reward_field: str = ""
    training_reward_scale: float | None = None
    task_start_score_field: float = 0.0
    task_target_score_field: float | None = None
    max_steps: int | None = None
    continue_on_fail: bool = True

    # --- Model & prompt ---
    action_format: str = ""
    action_space_mode: str = ""
    history_context_mode: str = ""
    initial_messages: list[dict[str, str]] = field(default_factory=list)

    # --- Controls ---
    role_controls: RoleControls = field(default_factory=RoleControls)
    unified_action_space_map: dict[str, dict[str, object]] = field(default_factory=dict)
    unified_action_space_specs: list[dict[str, object]] = field(default_factory=list)
