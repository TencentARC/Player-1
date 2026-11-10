"""Deterministic trial ledger for the MineDojo programmatic 1.16.5 port."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

MINEDOJO_PORTED_PROTOCOL = "minedojo_programmatic_ported_1_16_5_kbm_v1"
MINEDOJO_PORTED_TRIALS_PER_TASK = 1

# These are model decisions at the maintained one-tick (50 ms) action
# boundary. They are the fixed port evaluation contract, not a claim about an
# unpublished MineDojo or SIMA timeout. Callers may explicitly override them
# only for smoke tests and ablations.
MINEDOJO_PORTED_CATEGORY_MAX_DECISIONS = {
    "combat": 1_000,
    "harvest": 1_000,
    "techtree": 1_000,
    # The two public Survival tasks target 100 Minecraft days. Their exact
    # target-derived horizon is resolved below instead of using this fallback.
    "survival": 2_400_000,
}


def _stable_seed(*parts: object) -> int:
    payload = "\0".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0x7FFFFFFF


def task_max_decisions(task: Mapping[str, Any]) -> int:
    """Resolve the fixed port horizon for one compiled task."""

    explicit = task.get("max_decisions")
    if explicit is not None:
        if isinstance(explicit, bool) or not isinstance(explicit, int) or explicit <= 0:
            raise ValueError(f"MineDojo-ported task {task.get('task_id')!r} has an invalid max_decisions")
        return explicit
    category = str(task.get("category") or "")
    try:
        default_max_decisions = MINEDOJO_PORTED_CATEGORY_MAX_DECISIONS[category]
    except KeyError as exc:
        raise ValueError(f"MineDojo-ported task has an unsupported category: {category!r}") from exc
    if category != "survival":
        return default_max_decisions
    target = task.get("target")
    threshold = target.get("gte") if isinstance(target, Mapping) else None
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold <= 0:
        raise ValueError(f"MineDojo-ported survival task {task.get('task_id')!r} has an invalid target")
    return max(default_max_decisions, int(threshold))


@dataclass(frozen=True)
class MineDojoPortedTrial:
    """One fully pinned rollout of a compiled Programmatic task."""

    rollout_id: str
    task_id: str
    category: str
    instruction: str
    guidance: str | None
    trial_index: int
    world_seed: int
    task_rng_seed: int
    max_decisions: int
    task: dict[str, Any]
    selection_suite_id: str | None = None
    selection_difficulty: str | None = None
    protocol: str = MINEDOJO_PORTED_PROTOCOL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def materialize_minedojo_ported_trials(
    manifest: Mapping[str, Any],
    *,
    trials_per_task: int = MINEDOJO_PORTED_TRIALS_PER_TASK,
    task_ids: Sequence[str] | None = None,
    max_decisions: int | None = None,
) -> tuple[MineDojoPortedTrial, ...]:
    """Create a deterministic ledger without depending on MineDojo at runtime."""

    if isinstance(trials_per_task, bool) or not isinstance(trials_per_task, int) or trials_per_task <= 0:
        raise ValueError("MineDojo-ported trials_per_task must be a positive integer")
    if max_decisions is not None and (
        isinstance(max_decisions, bool) or not isinstance(max_decisions, int) or max_decisions <= 0
    ):
        raise ValueError("MineDojo-ported max_decisions override must be a positive integer")
    raw_tasks = manifest.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("MineDojo-ported manifest must contain tasks")
    tasks = [dict(task) for task in raw_tasks if isinstance(task, Mapping)]
    if len(tasks) != len(raw_tasks):
        raise ValueError("MineDojo-ported manifest tasks must be mappings")
    by_id = {str(task.get("task_id")): task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("MineDojo-ported manifest task IDs must be unique")
    selected = list(task_ids or ())
    if len(set(selected)) != len(selected):
        raise ValueError("MineDojo-ported task selection cannot contain duplicates")
    if selected:
        missing = sorted(set(selected) - set(by_id))
        if missing:
            raise ValueError(f"Unknown MineDojo-ported task IDs: {', '.join(missing)}")
        tasks = [by_id[task_id] for task_id in selected]

    trials: list[MineDojoPortedTrial] = []
    for task in tasks:
        task_id = str(task["task_id"])
        for trial_index in range(trials_per_task):
            trials.append(
                MineDojoPortedTrial(
                    rollout_id=f"{task_id}.trial-{trial_index:03d}",
                    task_id=task_id,
                    category=str(task["category"]),
                    instruction=str(task["prompt"]),
                    guidance=(str(task["guidance"]) if task.get("guidance") is not None else None),
                    trial_index=trial_index,
                    world_seed=_stable_seed(MINEDOJO_PORTED_PROTOCOL, task_id, trial_index, "world"),
                    task_rng_seed=_stable_seed(MINEDOJO_PORTED_PROTOCOL, task_id, trial_index, "task"),
                    max_decisions=max_decisions or task_max_decisions(task),
                    task=task,
                )
            )
    return tuple(trials)


__all__ = [
    "MINEDOJO_PORTED_CATEGORY_MAX_DECISIONS",
    "MINEDOJO_PORTED_PROTOCOL",
    "MINEDOJO_PORTED_TRIALS_PER_TASK",
    "MineDojoPortedTrial",
    "materialize_minedojo_ported_trials",
    "task_max_decisions",
]
