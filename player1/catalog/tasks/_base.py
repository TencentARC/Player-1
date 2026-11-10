"""Typed task catalog records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .._yaml import (
    require_bool,
    require_float,
    require_mapping,
    require_nonempty_text,
    require_optional_float,
    require_optional_int,
    require_optional_text,
    require_text,
    validate_mapping_fields,
)


_TASK_FIELDS = {
    "task_id",
    "game_id",
    "task_prompt",
    "game_url_suffix",
    "evaluator_id",
    "evaluator_config",
    "training_reward_field",
    "training_reward_scale",
    "task_start_score_field",
    "task_target_score_field",
    "pause_during_inference",
    "max_steps",
    "continue_on_fail",
}

_LEGACY_TASK_FIELDS = {"task_goal": "task_prompt"}


@dataclass(slots=True)
class TaskSpec:
    """Task definition loaded from one task YAML file."""

    task_id: str
    game_id: str
    task_prompt: str = ""
    game_url_suffix: str | None = None
    evaluator_id: str = "noop"
    evaluator_config: dict[str, object] = field(default_factory=dict)
    training_reward_field: str = ""
    training_reward_scale: float | None = None
    task_start_score_field: float = 0.0
    task_target_score_field: float | None = None
    pause_during_inference: bool = True
    max_steps: int | None = None
    continue_on_fail: bool = True

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
    ) -> TaskSpec:
        """Parse a task definition from YAML data."""
        raw = require_mapping(data, owner="Task definition")
        validate_mapping_fields(
            raw,
            owner="Task definition",
            supported_fields=_TASK_FIELDS,
            deprecated_fields=_LEGACY_TASK_FIELDS,
        )

        task_id = require_nonempty_text(raw["task_id"], owner="task.task_id") if "task_id" in raw else None
        game_id = require_nonempty_text(raw["game_id"], owner="task.game_id") if "game_id" in raw else None
        task_prompt = require_text(raw["task_prompt"], owner="task.task_prompt") if "task_prompt" in raw else ""
        training_reward_field = (
            require_text(raw["training_reward_field"], owner="task.training_reward_field").strip()
            if "training_reward_field" in raw
            else ""
        )
        missing = []
        if not task_id:
            missing.append("task_id")
        if not game_id:
            missing.append("game_id")
        if not task_prompt.strip():
            missing.append("task_prompt")
        if game_id and game_id.strip().lower().replace("-", "_").startswith("base") and not training_reward_field:
            missing.append("training_reward_field")
        if missing:
            raise ValueError(f"Task YAML missing required field(s): {', '.join(missing)}")

        return cls(
            task_id=task_id,
            game_id=game_id,
            task_prompt=task_prompt,
            game_url_suffix=(
                require_optional_text(raw["game_url_suffix"], owner="task.game_url_suffix")
                if "game_url_suffix" in raw
                else None
            ),
            evaluator_id=(
                require_nonempty_text(raw["evaluator_id"], owner="task.evaluator_id")
                if "evaluator_id" in raw
                else "noop"
            ),
            evaluator_config=(
                require_mapping(raw["evaluator_config"], owner="task.evaluator_config")
                if "evaluator_config" in raw
                else {}
            ),
            training_reward_field=training_reward_field,
            training_reward_scale=(
                None
                if raw.get("training_reward_scale") is None
                else require_float(
                    raw["training_reward_scale"],
                    owner="task.training_reward_scale",
                    positive=True,
                )
            ),
            task_start_score_field=(
                require_float(raw["task_start_score_field"], owner="task.task_start_score_field")
                if "task_start_score_field" in raw
                else 0.0
            ),
            task_target_score_field=(
                require_optional_float(raw["task_target_score_field"], owner="task.task_target_score_field")
                if "task_target_score_field" in raw
                else None
            ),
            pause_during_inference=(
                require_bool(raw["pause_during_inference"], owner="task.pause_during_inference")
                if "pause_during_inference" in raw
                else True
            ),
            max_steps=(
                require_optional_int(raw["max_steps"], owner="task.max_steps", positive=True)
                if "max_steps" in raw
                else None
            ),
            continue_on_fail=(
                require_bool(raw["continue_on_fail"], owner="task.continue_on_fail")
                if "continue_on_fail" in raw
                else True
            ),
        )
