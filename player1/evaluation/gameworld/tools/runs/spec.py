"""Benchmark experiment YAML loading and run expansion."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from catalog import list_games, list_tasks, load_game
from catalog._yaml import load_yaml_mapping
from agents.mm_agents import list_models

RunRecord = dict[str, Any]
ALL_MODEL_TOKEN = "all"
ALL_CATALOG_TOKEN = "all"
DEPRECATED_ALL_MODEL_TOKENS = {"*", "all_models", "all-models"}


@dataclass(frozen=True)
class ExperimentSpec:
    path: Path
    name: str
    config: dict[str, Any]
    runs: list[RunRecord]
    repeat_waves: list[list[RunRecord]]


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"Experiment field `{field_name}` must be a list.")
    return value


def read_experiment_yaml(path: Path) -> dict[str, Any]:
    return load_yaml_mapping(path)


def run_dir_name(run: RunRecord) -> str:
    return (
        f"run_{int(run['run_index']):03d}_"
        f"{run['game_id']}_{run['task_id']}_{run['model_spec']}"
    )


def resolve_experiment_path(raw_path: str) -> Path:
    experiment_path = Path(raw_path).expanduser()
    if not experiment_path.is_absolute():
        experiment_path = (Path.cwd() / experiment_path).resolve()
    if not experiment_path.exists():
        raise SystemExit(f"Experiment not found: {experiment_path}")
    return experiment_path


def group_runs_by_repeat(runs: list[RunRecord]) -> list[list[RunRecord]]:
    grouped: dict[int, list[RunRecord]] = defaultdict(list)
    for run in runs:
        grouped[int(run["repeat_index"])].append(run)
    return [grouped[index] for index in sorted(grouped)]


def _validate_case_shape(case: dict[str, Any]) -> None:
    if "task" in case:
        raise ValueError(
            "Experiment cases must use `tasks`; singular `task` is not supported."
        )
    if "model" in case:
        raise ValueError(
            "Experiment cases must use `models`; singular `model` is not supported."
        )
    if "game" not in case or "tasks" not in case or "models" not in case:
        raise ValueError(f"Case must include game, tasks, and models: {case!r}")


def _is_all(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() == ALL_CATALOG_TOKEN
    if isinstance(value, list):
        tokens = [str(item).strip() for item in value if str(item).strip()]
        return tokens == [ALL_CATALOG_TOKEN]
    return False


def _expand_games(raw_game: Any) -> list[str]:
    game_id = str(raw_game).strip()
    if game_id == ALL_CATALOG_TOKEN:
        return list_games()
    return [game_id] if game_id else []


def _expand_tasks(raw_tasks: Any, *, game_id: str) -> list[str]:
    if _is_all(raw_tasks):
        return list_tasks(game_id)
    return [
        str(item).strip()
        for item in _require_list(raw_tasks, "tasks")
        if str(item).strip()
    ]


def _parse_models(raw_models: Any) -> list[str]:
    if isinstance(raw_models, str):
        if raw_models.strip() == ALL_MODEL_TOKEN:
            return [ALL_MODEL_TOKEN]
        raise ValueError("Experiment field `models` must be a list or the token `all`.")
    return [
        str(item).strip()
        for item in _require_list(raw_models, "models")
        if str(item).strip()
    ]


def _expand_model_spec(
    raw: str, *, role_count: int, all_models: list[str]
) -> list[str]:
    model = raw.strip()
    if not model:
        return []
    if model in DEPRECATED_ALL_MODEL_TOKENS:
        raise ValueError(
            "Use `models: all`; `*`, `all_models`, and `all-models` are unsupported."
        )
    if model == ALL_MODEL_TOKEN:
        return [",".join([name] * role_count) for name in all_models]

    parts = [part.strip() for part in model.split(",") if part.strip()]
    if not parts:
        return []
    if len(parts) == 1 and role_count > 1:
        return [",".join([parts[0]] * role_count)]
    if len(parts) == role_count:
        return [",".join(parts)]
    raise ValueError(
        f"Model spec '{model}' does not match role count={role_count}. "
        f"Use one model token or exactly {role_count} comma-separated models."
    )


def expand_runs(
    experiment: dict[str, Any], all_models: list[str] | None = None
) -> list[RunRecord]:
    runs: list[RunRecord] = []
    resolved_all_models = list(all_models) if all_models is not None else list_models()
    for case in _require_list(experiment.get("cases"), "cases"):
        if not isinstance(case, dict):
            raise ValueError(f"Invalid case: {case!r}")
        _validate_case_shape(case)

        game_ids = _expand_games(case["game"])
        if len(game_ids) > 1 and not _is_all(case["tasks"]):
            raise ValueError("Experiment cases with `game: all` must use `tasks: all`.")
        raw_models = _parse_models(case["models"])
        repeat = max(1, int(case.get("repeat") or 1))
        if not game_ids or not raw_models:
            raise ValueError(
                f"Case must include non-empty game, tasks, and models: {case!r}"
            )

        for repeat_index in range(1, repeat + 1):
            for game_id in game_ids:
                tasks = _expand_tasks(case["tasks"], game_id=game_id)
                if not tasks:
                    raise ValueError(f"No tasks found for game '{game_id}'.")

                role_count = len(load_game(game_id).game_roles)
                expanded_model_values: list[str] = []
                for raw_model in raw_models:
                    expanded_model_values.extend(
                        _expand_model_spec(
                            raw_model,
                            role_count=role_count,
                            all_models=resolved_all_models,
                        )
                    )
                resolved_model_values = list(dict.fromkeys(expanded_model_values))

                for task_id in tasks:
                    for model_spec in resolved_model_values:
                        runs.append(
                            {
                                "run_index": len(runs) + 1,
                                "preset": f"{game_id}+{task_id}+{model_spec}",
                                "game_id": game_id,
                                "task_id": task_id,
                                "model_spec": model_spec,
                                "repeat_index": repeat_index,
                            }
                        )
    return runs


def load_experiment(path: Path) -> ExperimentSpec:
    experiment = read_experiment_yaml(path)
    runs = expand_runs(experiment)
    if not runs:
        raise ValueError("No runs expanded from experiment.")

    experiment_name = (
        str(experiment.get("experiment_name") or path.stem).strip() or "benchmark"
    )
    return ExperimentSpec(
        path=path,
        name=experiment_name,
        config=experiment,
        runs=runs,
        repeat_waves=group_runs_by_repeat(runs),
    )
