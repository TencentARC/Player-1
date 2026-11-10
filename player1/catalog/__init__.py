"""Catalog-based preset configuration system.

Usage:
    from player1.catalog import build_runtime_config

    config = build_runtime_config(
        "base_3d_aim+base_3d_aim_train+qwen3.5-baserl"
    )
"""

from __future__ import annotations

from .games import get_game_definition_path, load_game, list_games, resolve_game_id
from .tasks import load_task, list_tasks
from .models import get_model_definition_path, load_model, list_models

__all__ = [
    "build_runtime_config",
    "get_game_definition_path",
    "load_game",
    "list_games",
    "resolve_game_id",
    "get_model_definition_path",
    "load_task",
    "list_tasks",
    "load_model",
    "list_models",
]


def __getattr__(name: str):
    if name != "build_runtime_config":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from .builder import build_runtime_config

    globals()[name] = build_runtime_config
    return build_runtime_config
