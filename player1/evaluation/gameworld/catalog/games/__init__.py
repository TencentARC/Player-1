"""Game catalog loader."""

from __future__ import annotations

from functools import cache, lru_cache
from pathlib import Path

from .._yaml import load_yaml_mapping
from ._base import GameDefinition

_GAMES_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _game_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}

    for path in sorted(_GAMES_DIR.rglob("*.yaml")):
        game_id = path.stem
        existing = index.get(game_id)
        if existing is None:
            index[game_id] = path
            continue
        duplicates.setdefault(game_id, [existing]).append(path)

    if duplicates:
        duplicate_text = ", ".join(
            f"{game_id}: {[str(path.relative_to(_GAMES_DIR)) for path in paths]}"
            for game_id, paths in sorted(duplicates.items())
        )
        raise ValueError(f"Duplicate game definition ids found: {duplicate_text}")

    return index


def list_games() -> list[str]:
    """List all available catalog game ids."""
    return sorted(_game_index())


def _format_known_games() -> str:
    known = list_games()
    preview = ", ".join(known[:8])
    suffix = ", ..." if len(known) > 8 else ""
    return f"{preview}{suffix}" if preview else "(none)"


def resolve_game_id(game_ref: str) -> str:
    """Validate and return an exact catalog game id."""
    game_id = str(game_ref or "").strip()
    if not game_id:
        raise ValueError("Game reference cannot be empty.")

    if game_id in _game_index():
        return game_id

    raise ValueError(
        f"Unknown game_id '{game_ref}'. Game ids must exactly match catalog YAML stems. "
        f"Known examples: {_format_known_games()}"
    )


def get_game_definition_path(game_id: str) -> Path:
    """Return the YAML path for a catalog game id."""
    resolved_id = resolve_game_id(game_id)
    path = _game_index().get(resolved_id)
    if path is None:
        raise FileNotFoundError(f"Game definition not found for id: {game_id}")
    return path


@cache
def _load_game_cached(game_id: str) -> GameDefinition:
    return GameDefinition.from_mapping(
        load_yaml_mapping(get_game_definition_path(game_id)),
        game_id=game_id,
    )


def load_game(game_id: str) -> GameDefinition:
    """Load a game definition by id."""
    return _load_game_cached(resolve_game_id(game_id))
