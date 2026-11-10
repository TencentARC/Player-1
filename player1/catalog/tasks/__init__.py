"""Task catalog loader."""

from __future__ import annotations

from pathlib import Path

from .._yaml import format_known_ids, load_yaml_mapping
from ..games import resolve_game_id
from ._base import TaskSpec

_TASKS_DIR = Path(__file__).parent


def _iter_task_definition_paths() -> list[Path]:
    nested = sorted(path for path in _TASKS_DIR.rglob("*.yaml") if path.parent != _TASKS_DIR)
    if nested:
        relative_paths = ", ".join(str(path.relative_to(_TASKS_DIR)) for path in nested)
        raise ValueError(
            "Task catalog must be flat; move nested task YAMLs directly under "
            f"{_TASKS_DIR}. Nested definitions: {relative_paths}"
        )
    return sorted(path for path in _TASKS_DIR.glob("*.yaml") if path.is_file())


def _load_task_definition(path: Path) -> TaskSpec:
    task = TaskSpec.from_mapping(load_yaml_mapping(path))
    if task.task_id != path.stem:
        raise ValueError(
            "Task YAML id mismatch: "
            f"file '{path.name}' expects task_id='{path.stem}', "
            f"but declares task_id='{task.task_id}'."
        )
    return task


def _get_task_definition_path(game_id: str, task_id: str) -> Path:
    _iter_task_definition_paths()
    path = _TASKS_DIR / f"{task_id}.yaml"
    if not path.is_file():
        known = list_tasks(game_id)
        known_examples = format_known_ids(known)
        known_text = f" Known examples: {known_examples}" if known_examples != "(none)" else ""
        raise FileNotFoundError(
            f"Task '{task_id}' not found for game '{game_id}'. "
            f"Task ids must exactly match catalog YAML stems. Searched: {path}.{known_text}"
        )
    return path


def load_task(game_id: str, task_id: str) -> TaskSpec:
    """Load one task definition for a game."""
    resolved_game_id = resolve_game_id(game_id)
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        raise ValueError("Task id cannot be empty.")
    path = _get_task_definition_path(resolved_game_id, normalized_task_id)
    task = _load_task_definition(path)
    if task.game_id != resolved_game_id:
        raise ValueError(
            "Task YAML game mismatch: "
            f"task_id='{normalized_task_id}' was requested for game_id='{resolved_game_id}', "
            f"but the file declares game_id='{task.game_id}'."
        )
    return task


def list_tasks(game_id: str | None = None) -> list[str]:
    """List available task ids."""
    paths = _iter_task_definition_paths()
    if game_id is None:
        return sorted(_load_task_definition(path).task_id for path in paths)

    resolved_game_id = resolve_game_id(game_id)
    return sorted(
        task.task_id for task in (_load_task_definition(path) for path in paths) if task.game_id == resolved_game_id
    )
