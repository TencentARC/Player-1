"""Joint-training configuration and deterministic environment batch schedules."""

from __future__ import annotations

from collections import Counter
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from player1.catalog._mixture import (
    _reject_unknown_keys,
    _require_identifier,
    _require_mapping,
    _require_positive_weight,
    _smooth_fixed_count_order,
    allocate_weighted_counts,
)


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    """One environment participating in a joint-training run."""

    environment_id: str
    train_preset_spec: str
    train_weight: float


@dataclass(frozen=True, slots=True)
class JointTrainingConfig:
    """Environment composition for a training run."""

    joint_training_id: str
    environments: tuple[EnvironmentSpec, ...]

    def environment(self, environment_id: str) -> EnvironmentSpec:
        for environment in self.environments:
            if environment.environment_id == environment_id:
                return environment
        raise KeyError(f"Unknown environment_id {environment_id!r} in {self.joint_training_id!r}")


@dataclass(frozen=True, slots=True)
class EnvironmentBatchSchedule:
    """Concrete environment order consumed by a sequential dataset sampler."""

    joint_training_id: str
    batch_size: int
    environment_ids: tuple[str, ...]

    @property
    def total_samples(self) -> int:
        return len(self.environment_ids)

    @property
    def environment_counts(self) -> dict[str, int]:
        return dict(Counter(self.environment_ids))

    def batches(self) -> tuple[tuple[str, ...], ...]:
        return tuple(
            self.environment_ids[start : start + self.batch_size]
            for start in range(0, self.total_samples, self.batch_size)
        )


def _require_nonempty_string(value: Any, *, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} must be non-empty")
    return result


def load_joint_training_config(path: str | Path) -> JointTrainingConfig:
    """Load and strictly validate a single- or multi-environment definition."""

    config_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(config_path.read_text())
    except FileNotFoundError:
        raise FileNotFoundError(f"Joint-training config does not exist: {config_path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in joint-training config {config_path}: {exc}") from exc

    config = _require_mapping(raw, field="joint-training config")
    _reject_unknown_keys(
        config,
        allowed={"joint_training_id", "environments"},
        field="joint-training config",
    )
    joint_training_id = _require_identifier(config.get("joint_training_id"), field="joint_training_id")

    raw_environments = config.get("environments")
    if not isinstance(raw_environments, list) or not raw_environments:
        raise ValueError("joint-training config requires at least one environment")

    environments: list[EnvironmentSpec] = []
    seen_environment_ids: set[str] = set()
    for index, raw_environment in enumerate(raw_environments):
        field = f"environments[{index}]"
        environment = _require_mapping(raw_environment, field=field)
        _reject_unknown_keys(
            environment,
            allowed={
                "environment_id",
                "train_preset_spec",
                "train_weight",
            },
            field=field,
        )
        environment_id = _require_identifier(environment.get("environment_id"), field=f"{field}.environment_id")
        if environment_id in seen_environment_ids:
            raise ValueError(f"Duplicate environment_id: {environment_id}")
        seen_environment_ids.add(environment_id)
        train_preset_spec = _require_nonempty_string(
            environment.get("train_preset_spec"),
            field=f"{field}.train_preset_spec",
        )
        environments.append(
            EnvironmentSpec(
                environment_id=environment_id,
                train_preset_spec=train_preset_spec,
                train_weight=_require_positive_weight(
                    environment.get("train_weight"), field=f"{field}.train_weight"
                ),
            )
        )

    return JointTrainingConfig(
        joint_training_id=joint_training_id,
        environments=tuple(environments),
    )


def _compile_training_ids(
    config: JointTrainingConfig,
    *,
    total_samples: int,
    batch_size: int,
) -> tuple[str, ...]:
    if total_samples <= 0:
        raise ValueError(f"train total_samples must be positive, got {total_samples}")
    if total_samples % batch_size != 0:
        raise ValueError(
            f"train total_samples={total_samples} must be divisible by batch_size={batch_size}; "
            "joint training never drops or partially consumes a global batch"
        )
    counts = allocate_weighted_counts(batch_size, [environment.train_weight for environment in config.environments])
    if any(count == 0 for count in counts):
        raise ValueError(
            f"batch_size={batch_size} is too small or train weights are too skewed to include every environment"
        )
    batch_order = _smooth_fixed_count_order(counts)
    batch_environment_ids = tuple(config.environments[index].environment_id for index in batch_order)
    return batch_environment_ids * (total_samples // batch_size)


def compile_environment_batch_schedule(
    config: JointTrainingConfig,
    *,
    batch_size: int,
    total_samples: int,
) -> EnvironmentBatchSchedule:
    """Compile the exact environment order for a sequential training dataset."""

    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    environment_ids = _compile_training_ids(
        config, total_samples=total_samples, batch_size=batch_size,
    )

    return EnvironmentBatchSchedule(
        joint_training_id=config.joint_training_id,
        batch_size=batch_size,
        environment_ids=environment_ids,
    )


__all__ = [
    "EnvironmentBatchSchedule",
    "EnvironmentSpec",
    "JointTrainingConfig",
    "allocate_weighted_counts",
    "compile_environment_batch_schedule",
    "load_joint_training_config",
]
