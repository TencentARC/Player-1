"""Catalog-based preset configuration system.

Usage:
    from catalog import build_runtime_config

    config = build_runtime_config(
        "12_fireboy-and-watergirl+12_01+gemini-2.5-computer-use,gemini-2.5-computer-use"
    )
"""

from .games import get_game_definition_path, load_game, list_games, resolve_game_id
from .tasks import load_task, list_tasks
from .builder import build_runtime_config

__all__ = [
    "build_runtime_config",
    "get_game_definition_path",
    "load_game",
    "list_games",
    "resolve_game_id",
    "load_task",
    "list_tasks",
]
