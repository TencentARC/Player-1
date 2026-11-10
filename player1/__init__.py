"""Player-1 training and evaluation integration for verl."""

from .catalog import build_runtime_config
from .runtime.bootstrap import (
    DEFAULT_PRESET_SPEC,
    configure_runtime,
    resolve_game_directory,
)

__all__ = [
    "DEFAULT_PRESET_SPEC",
    "build_runtime_config",
    "configure_runtime",
    "resolve_game_directory",
]
