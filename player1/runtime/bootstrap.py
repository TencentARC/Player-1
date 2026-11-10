"""Workspace and catalog access for Player-1."""

from __future__ import annotations

import logging
import os
from pathlib import Path

DEFAULT_PRESET_SPEC = "base_3d_aim+base_3d_aim_train+qwen3.5-baserl"
DEFAULT_RUNTIME_SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAMES_ROOT = DEFAULT_RUNTIME_SOURCE_ROOT / "gym"
GAME_COLLECTION_NAMES = ("player1-gym",)

_RUNTIME_LOG_LEVELS = {
    "model": 25,
    "game": 26,
    "task": 27,
    "env": 28,
}


def _build_level_logger(level: int):
    def _log(self, message, *args, **kwargs):
        if self.isEnabledFor(level):
            self._log(level, message, args, **kwargs)

    return _log


def install_runtime_logging() -> None:
    """Install the custom log levels used by the canonical Player-1 runtime."""

    for method_name, level in _RUNTIME_LOG_LEVELS.items():
        logging.addLevelName(level, method_name.upper())
        if not hasattr(logging.Logger, method_name):
            setattr(logging.Logger, method_name, _build_level_logger(level))


def runtime_source_root() -> Path:
    """Return the Player-1 source tree beside this module."""

    root = DEFAULT_RUNTIME_SOURCE_ROOT.resolve()
    if not (root / "runtime" / "contracts.py").is_file() or not (root / "catalog" / "__init__.py").is_file():
        raise FileNotFoundError(f"Player-1 source tree is incomplete: {root}")
    return root


def games_root() -> Path:
    raw_root = os.getenv("PLAYER1_GAMES_ROOT")
    root = Path(raw_root).expanduser() if raw_root else DEFAULT_GAMES_ROOT
    return root.resolve()


def collection_root() -> Path:
    root = games_root()
    if not (root / "collection.json").is_file():
        raise FileNotFoundError(f"Player-1 game collection does not exist: {root}")
    return root


def training_games_root() -> Path:
    """Use the published Gym collection for training and direct interaction."""
    return collection_root()


def configure_runtime() -> Path:
    """Install runtime logging and configure the bundled game-assets root."""

    install_runtime_logging()
    source_root = runtime_source_root()
    os.environ.setdefault("PLAYER1_GAMES_ROOT", str(games_root()))
    return source_root


def resolve_game_directory(game_name: str | os.PathLike[str]) -> Path:
    maintained_root = collection_root()
    candidate = Path(game_name).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (maintained_root / candidate).resolve()
    try:
        relative_game = resolved.relative_to(maintained_root)
    except ValueError as error:
        raise ValueError(
            f"Player-1 games must remain under the bundled game collection {maintained_root}: {resolved}"
        ) from error
    if not relative_game.parts:
        raise ValueError(f"Player-1 game must name a directory below {maintained_root}")
    if not resolved.is_dir():
        raise FileNotFoundError(f"Player-1 game does not exist: {resolved}")
    return resolved


__all__ = [
    "DEFAULT_GAMES_ROOT",
    "DEFAULT_PRESET_SPEC",
    "DEFAULT_RUNTIME_SOURCE_ROOT",
    "configure_runtime",
    "games_root",
    "resolve_game_directory",
    "runtime_source_root",
    "collection_root",
    "training_games_root",
    "GAME_COLLECTION_NAMES",
]
