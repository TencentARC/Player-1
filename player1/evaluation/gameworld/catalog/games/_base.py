"""Typed game catalog records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .._yaml import (
    as_bool,
    as_float,
    as_int,
    as_mapping,
    as_mapping_list,
    as_optional_text,
    as_string_float_mapping,
    as_string_list,
    as_string_set,
    as_text,
)

_SUPPORTED_PRIMITIVE_ACTIONS = frozenset(
    {
        "click",
        "click_hold",
        "drag",
        "mouse_move",
        "press_key",
        "press_keys",
        "scroll",
        "type",
        "wait",
    }
)


class PlayerMode(str, Enum):
    """Multiplayer mode for a game."""

    SINGLE = "single"
    COOPERATIVE = "cooperative"
    COMPETITIVE = "competitive"

    @classmethod
    def from_value(cls, value: Any) -> PlayerMode:
        """Parse a raw catalog value into a known player mode."""
        candidate = as_optional_text(value) or cls.SINGLE.value
        try:
            return cls(candidate)
        except ValueError:
            return cls.SINGLE


@dataclass(slots=True)
class RoleControls:
    """Keyboard and mouse constraints for one player role."""

    allowed_keys: set[str] = field(default_factory=set)
    hold_duration: float = 0.1
    key_durations: dict[str, float] = field(default_factory=dict)
    allow_clicks: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> RoleControls:
        """Parse control limits from a YAML mapping."""
        raw = as_mapping(data)
        return cls(
            allowed_keys=as_string_set(raw.get("allowed_keys")),
            hold_duration=as_float(raw.get("hold_duration"), default=0.1),
            key_durations=as_string_float_mapping(raw.get("key_durations")),
            allow_clicks=as_bool(raw.get("allow_clicks"), default=True),
        )

    def copy(self) -> RoleControls:
        """Return an independent copy for runtime use."""
        return RoleControls(
            allowed_keys=set(self.allowed_keys),
            hold_duration=self.hold_duration,
            key_durations=dict(self.key_durations),
            allow_clicks=self.allow_clicks,
        )


@dataclass(slots=True)
class SemanticControls:
    """Semantic control definition for non-CUA agents."""

    action_id: str
    description: str = ""
    binding: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> SemanticControls:
        """Parse a semantic action entry from YAML."""
        raw = as_mapping(data)
        action_id = as_optional_text(raw.get("id"))
        if not action_id:
            raise ValueError("Semantic control entry missing required field: id")

        binding = as_mapping(raw.get("binding"))
        if not binding:
            raise ValueError(
                f"Semantic control '{action_id}' missing required field: binding"
            )
        binding_action = as_optional_text(binding.get("action"))
        if binding_action not in _SUPPORTED_PRIMITIVE_ACTIONS:
            raise ValueError(
                f"Semantic control '{action_id}' has unsupported binding action: "
                f"{binding_action or '<missing>'}"
            )
        if binding_action == "press_key":
            if not as_optional_text(binding.get("key")) or "keys" in binding:
                raise ValueError(
                    f"Semantic control '{action_id}' press_key binding requires singular 'key'"
                )
        if binding_action == "press_keys":
            keys = as_string_list(binding.get("keys"))
            if not keys or "key" in binding:
                raise ValueError(
                    f"Semantic control '{action_id}' press_keys binding requires plural 'keys'"
                )

        return cls(
            action_id=action_id,
            description=as_text(raw.get("description")),
            binding=binding,
            parameters=as_mapping(raw.get("parameters")),
            required=as_string_list(raw.get("required")),
        )

    def to_runtime_spec(self) -> dict[str, object]:
        """Convert the semantic control into the runtime JSON-like schema."""
        return {
            "id": self.action_id,
            "description": self.description,
            "binding": dict(self.binding),
            "parameters": dict(self.parameters),
            "required": list(self.required),
        }


@dataclass(slots=True)
class RolePromptSections:
    """Prompt fragments attached to a player role."""

    role_section: str = ""
    computer_use_controls_section: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> RolePromptSections:
        """Parse prompt blocks from YAML."""
        raw = as_mapping(data)
        return cls(
            role_section=as_text(raw.get("role_section")),
            computer_use_controls_section=as_text(
                raw.get("computer_use_controls_section")
            ),
        )


@dataclass(slots=True)
class PlayerRole:
    """Definition of one controllable role in a game."""

    name: str
    controls: RoleControls = field(default_factory=RoleControls)
    semantic_controls: list[SemanticControls] = field(default_factory=list)
    prompt: RolePromptSections = field(default_factory=RolePromptSections)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> PlayerRole:
        """Parse one player role from YAML."""
        raw = as_mapping(data)

        return cls(
            name=as_optional_text(raw.get("name")) or "player",
            controls=RoleControls.from_mapping(raw.get("computer_use_controls")),
            semantic_controls=[
                SemanticControls.from_mapping(control_data)
                for control_data in as_mapping_list(raw.get("semantic_controls"))
            ],
            prompt=RolePromptSections.from_mapping(raw.get("prompt")),
        )


@dataclass(slots=True)
class GameDefinition:
    """Shared game definition loaded from catalog YAML."""

    game_id: str
    game_rules: str = ""
    player_mode: PlayerMode = PlayerMode.SINGLE
    game_roles: list[PlayerRole] = field(default_factory=list)
    speed_multiplier: float = 1.0
    width: int = 1280
    height: int = 720
    url: str | None = None

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
        *,
        game_id: str,
    ) -> GameDefinition:
        """Parse a game definition from a YAML mapping."""
        raw = as_mapping(data)

        return cls(
            game_id=game_id,
            game_rules=as_text(raw.get("game_rules")),
            player_mode=PlayerMode.from_value(raw.get("player_mode")),
            game_roles=[
                PlayerRole.from_mapping(item)
                for item in as_mapping_list(raw.get("game_roles"))
            ],
            speed_multiplier=as_float(raw.get("speed_multiplier"), default=1.0),
            width=as_int(raw.get("width"), default=1280),
            height=as_int(raw.get("height"), default=720),
            url=as_optional_text(raw.get("url")),
        )

    @property
    def role_count(self) -> int:
        """Number of roles defined for the game."""
        return len(self.game_roles)
