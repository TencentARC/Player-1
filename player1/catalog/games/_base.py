"""Typed game catalog records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from player1.agents.actions.prompting import InContextExample
from player1.agents.actions.control import ACTION_SPACE_MODE, require_action_space_mode
from player1.runtime.config import DEFAULT_GAME_HEIGHT, DEFAULT_GAME_WIDTH
from player1.runtime.types import GameControls

from .._yaml import (
    require_bool,
    require_int,
    require_mapping,
    require_nonempty_text,
    require_text,
    validate_mapping_fields,
)

_LEGACY_ROLE_FIELDS = {
    "prompt": "role_control_block",
    "semantic_controls": "game_controls",
    "action_controls": "game_controls",
    "unified_action_tools": "game_controls",
    "computer_use_controls": "game_controls",
}

_LEGACY_GAME_FIELDS = {
    "player_role": "role_control",
    "in_context_example": "in_context_examples",
}

_GAME_FIELDS = {
    "game_name",
    "game_rules",
    "role_control",
    "in_context_examples",
    "width",
    "height",
}

_IN_CONTEXT_EXAMPLE_MODES = frozenset({ACTION_SPACE_MODE})


def _parse_game_controls(data: Any) -> GameControls:
    """Parse catalog YAML into the framework-neutral runtime DTO."""

    raw = require_mapping(data, owner="role_control.game_controls")
    validate_mapping_fields(
        raw,
        owner="Game controls",
        supported_fields={"duration_ms", "keys", "mouse_move", "mouse_click", "mouse_hold"},
    )
    return GameControls(
        duration_ms=(
            require_int(raw["duration_ms"], owner="game_controls.duration_ms", positive=True)
            if "duration_ms" in raw
            else 200
        ),
        keys=_parse_keys(raw["keys"]) if "keys" in raw else [],
        mouse_move=_parse_mouse_move(raw["mouse_move"]) if "mouse_move" in raw else False,
        mouse_click=_parse_mouse_buttons(raw["mouse_click"], field="mouse_click") if "mouse_click" in raw else [],
        mouse_hold=_parse_mouse_buttons(raw["mouse_hold"], field="mouse_hold") if "mouse_hold" in raw else [],
    )


def _parse_keys(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("game_controls.keys must be a list of key names.")

    parsed: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("game_controls.keys items must be strings.")
        key = item.strip().lower()

        if not key or key in seen:
            continue
        seen.add(key)
        parsed.append(key)
    return parsed


def _parse_mouse_move(value: Any) -> bool:
    return require_bool(value, owner="game_controls.mouse_move")


def _parse_mouse_buttons(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"game_controls.{field} must be a list of mouse button names.")

    parsed: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"game_controls.{field} items must be strings.")
        button = item.strip().lower()
        if not button or button in seen:
            continue
        seen.add(button)
        parsed.append(button)
    return parsed


@dataclass(slots=True)
class RoleControl:
    """Role-specific controls and prompt block for a game."""

    game_controls: GameControls
    role_control_block: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> RoleControl:
        """Parse one role-control definition from YAML."""
        raw = require_mapping(data, owner="Role control")
        validate_mapping_fields(
            raw,
            owner="Role control",
            supported_fields={"role_control_block", "game_controls"},
            deprecated_fields=_LEGACY_ROLE_FIELDS,
        )
        if "game_controls" not in raw:
            raise ValueError("Role control missing required field: game_controls")

        return cls(
            game_controls=_parse_game_controls(raw["game_controls"]),
            role_control_block=(
                require_text(raw["role_control_block"], owner="role_control.role_control_block")
                if "role_control_block" in raw
                else ""
            ),
        )

    def require_role_control_block(self, action_space_mode: str) -> str:
        """Return the shared role prose for the production action contract."""

        require_action_space_mode(action_space_mode)
        return self.role_control_block


@dataclass(slots=True)
class GameDefinition:
    """Shared game definition loaded from catalog YAML."""

    game_name: str
    role_control: RoleControl
    game_rules: str = ""
    in_context_examples: dict[str, tuple[InContextExample, ...]] = field(default_factory=dict)
    width: int = DEFAULT_GAME_WIDTH
    height: int = DEFAULT_GAME_HEIGHT

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> GameDefinition:
        """Parse a game definition from a YAML mapping."""
        raw = require_mapping(data, owner="Game definition")
        validate_mapping_fields(
            raw,
            owner="Game definition",
            supported_fields=_GAME_FIELDS,
            deprecated_fields=_LEGACY_GAME_FIELDS,
        )
        game_name = require_nonempty_text(raw["game_name"], owner="game.game_name") if "game_name" in raw else None
        if not game_name:
            raise ValueError("Game definition missing required field: game_name")
        if "role_control" not in raw:
            raise ValueError("Game definition missing required field: role_control")
        if "in_context_examples" not in raw:
            raise ValueError("Game definition missing required field: in_context_examples")

        return cls(
            game_name=game_name,
            game_rules=(require_text(raw["game_rules"], owner="game.game_rules") if "game_rules" in raw else ""),
            in_context_examples=_parse_in_context_examples(raw["in_context_examples"]),
            role_control=RoleControl.from_mapping(raw["role_control"]),
            width=(require_int(raw["width"], owner="game.width", positive=True) if "width" in raw else DEFAULT_GAME_WIDTH),
            height=(require_int(raw["height"], owner="game.height", positive=True) if "height" in raw else DEFAULT_GAME_HEIGHT),
        )

    def require_in_context_examples(
        self, action_space_mode: str, *, variant: str = "original"
    ) -> tuple[InContextExample, ...]:
        """Select one complete example group; the original group remains the default."""

        mode = require_action_space_mode(action_space_mode)
        key = f"{variant}_{mode}"
        examples = self.in_context_examples.get(key)
        if examples is None:
            raise ValueError(f"Game '{self.game_name}' has no in-context example group {key!r}.")
        return examples


def _parse_in_context_examples(value: Any) -> dict[str, tuple[InContextExample, ...]]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("in_context_examples must be a non-empty mapping of example groups.")

    supported_groups = {f"{variant}_{mode}" for variant in ("original", "basic") for mode in _IN_CONTEXT_EXAMPLE_MODES}
    parsed: dict[str, tuple[InContextExample, ...]] = {}
    for raw_key, raw_examples in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("in_context_examples group keys must be non-empty strings.")
        key = raw_key.strip()
        # Single-group catalogs in other benchmarks still use the action-space key.
        if key in _IN_CONTEXT_EXAMPLE_MODES:
            key = f"original_{key}"
        if key in parsed:
            raise ValueError(f"in_context_examples contains duplicate example group {key!r}.")
        if key not in supported_groups:
            expected = ", ".join(sorted(supported_groups))
            raise ValueError(f"in_context_examples has unsupported example group {key!r}; expected {expected}.")
        if not isinstance(raw_examples, list) or not raw_examples:
            raise ValueError(f"in_context_examples.{key} must be a non-empty list of named examples.")

        mode_examples: list[InContextExample] = []
        seen_names: set[str] = set()
        for index, raw_example in enumerate(raw_examples, start=1):
            owner = f"in_context_examples.{key}[{index}]"
            example = require_mapping(raw_example, owner=owner)
            validate_mapping_fields(
                example,
                owner=owner,
                supported_fields={"name", "response"},
            )
            if set(example) != {"name", "response"}:
                raise ValueError(f"{owner} must define exactly name and response.")
            name = require_nonempty_text(example.get("name"), owner=f"{owner}.name")
            response = require_nonempty_text(example.get("response"), owner=f"{owner}.response")
            if "\n" in name or name.endswith(":"):
                raise ValueError(f"{owner}.name must be single-line text without a trailing colon.")
            normalized_name = name.casefold()
            if normalized_name in seen_names:
                raise ValueError(f"in_context_examples.{key} contains duplicate name {name!r}.")
            seen_names.add(normalized_name)
            mode_examples.append(InContextExample(name=name, response=response))
        parsed[key] = tuple(mode_examples)

    required = {f"original_{mode}" for mode in _IN_CONTEXT_EXAMPLE_MODES}
    if not required.issubset(parsed):
        raise ValueError(f"in_context_examples must define the original groups: {', '.join(sorted(required))}.")
    return parsed
