"""Typed task catalog records."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .._yaml import (
    as_mapping,
    as_optional_text,
    as_text,
)


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_objective(evaluator_config: Mapping[str, Any]) -> None:
    objective = evaluator_config.get("objective")
    if not isinstance(objective, Mapping):
        raise ValueError("Task requires evaluator_config.objective")

    reach = objective.get("reach")
    if not isinstance(reach, Mapping) or not reach:
        raise ValueError("evaluator_config.objective.reach must be a non-empty mapping")
    for field_path, target_spec in reach.items():
        if not isinstance(field_path, str) or not field_path.strip():
            raise ValueError("objective target paths must be non-empty strings")
        if isinstance(target_spec, Mapping):
            if "target" not in target_spec:
                raise ValueError(f"objective target '{field_path}' requires target")
            start = target_spec.get("start", 0)
            target = target_spec.get("target")
        else:
            start = 0
            target = target_spec
        if not _is_finite_number(start) or not _is_finite_number(target):
            raise ValueError(f"objective target '{field_path}' must use finite numbers")
        if float(target) <= float(start):
            raise ValueError(
                f"objective target '{field_path}' must be greater than start"
            )

    requirements = objective.get("require")
    if requirements is not None:
        if not isinstance(requirements, Mapping) or not requirements:
            raise ValueError(
                "evaluator_config.objective.require must be a non-empty mapping"
            )
        for field_path in requirements:
            if not isinstance(field_path, str) or not field_path.strip():
                raise ValueError(
                    "objective requirement paths must be non-empty strings"
                )


@dataclass(slots=True)
class TaskSpec:
    """Task definition loaded from one task YAML file."""

    task_id: str
    game_id: str
    task_prompt: str
    evaluator_config: dict[str, object]
    game_url_suffix: str | None = None

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
        *,
        task_id: str,
        game_id: str,
    ) -> TaskSpec:
        """Parse a task definition from YAML data."""
        raw = as_mapping(data)
        task_prompt = as_text(raw.get("task_prompt"))
        if not task_prompt.strip():
            raise ValueError("Task YAML missing required field: task_prompt")

        evaluator_config = as_mapping(raw.get("evaluator_config"))
        _validate_objective(evaluator_config)

        return cls(
            task_id=task_id,
            game_id=game_id,
            task_prompt=task_prompt,
            game_url_suffix=as_optional_text(raw.get("game_url_suffix")),
            evaluator_config=evaluator_config,
        )
