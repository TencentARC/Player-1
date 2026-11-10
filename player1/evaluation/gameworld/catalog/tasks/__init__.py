"""Task catalog loader."""

from __future__ import annotations

from pathlib import Path

from .._yaml import load_yaml_mapping
from ..games import resolve_game_id
from ._base import TaskSpec

_TASKS_DIR = Path(__file__).parent


def _get_task_definition_path(game_id: str, task_id: str) -> Path:
    path = _TASKS_DIR / game_id / f"{task_id}.yaml"
    if not path.exists():
        game_tasks_dir = _TASKS_DIR / game_id
        known = (
            sorted(item.stem for item in game_tasks_dir.glob("*.yaml"))
            if game_tasks_dir.exists()
            else []
        )
        examples = ", ".join(known[:8])
        suffix = ", ..." if len(known) > 8 else ""
        known_text = f" Known examples: {examples}{suffix}" if examples else ""
        raise FileNotFoundError(
            f"Task '{task_id}' not found for game '{game_id}'. "
            f"Task ids must exactly match catalog YAML stems. Searched: {path}.{known_text}"
        )
    return path


def load_task(game_id: str, task_id: str) -> TaskSpec:
    """Load one task definition for a game."""
    resolved_game_id = resolve_game_id(game_id)
    normalized_task_id = str(task_id or "").strip()
    path = _get_task_definition_path(resolved_game_id, normalized_task_id)
    return TaskSpec.from_mapping(
        load_yaml_mapping(path),
        game_id=resolved_game_id,
        task_id=normalized_task_id,
    )


def list_tasks(game_id: str | None = None) -> list[str]:
    """List available task ids."""
    if game_id is None:
        return sorted({path.stem for path in _TASKS_DIR.rglob("*.yaml")})

    resolved_game_id = resolve_game_id(game_id)
    game_tasks_dir = _TASKS_DIR / resolved_game_id
    if not game_tasks_dir.exists():
        return []
    return sorted(path.stem for path in game_tasks_dir.glob("*.yaml"))
