"""Catalog-driven Player-1 prompts, tools, and action parsing."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from player1.agents.actions import (
    ACTION_SPACE_MODE,
    build_unified_action_space_map,
    build_unified_action_space_tools,
    inspect_unified_action_output,
    validate_in_context_examples,
)
from player1.agents.actions.parser import PlayerOneActionParser
from player1.agents.prompting import render_initial_messages
from player1.catalog.games import load_game
from player1.catalog.models import load_model

DEFAULT_MINECRAFT_GAME_ID = "minecraft_minestudio"
DEFAULT_MODEL_PROFILE_ID = "qwen3.5-player1-control-baserl"


@dataclass(frozen=True)
class AgentConfig:
    game_id: str = DEFAULT_MINECRAFT_GAME_ID
    model_profile_id: str = DEFAULT_MODEL_PROFILE_ID
    in_context_example_variant: str = "original"

    def __post_init__(self) -> None:
        if not self.game_id.strip() or not self.model_profile_id.strip():
            raise ValueError("Player-1 game and model profile IDs cannot be empty")


class GameAgent:
    """Build prompts, native tools, and actions through Player-1's shared contract."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.game = load_game(self.config.game_id)
        self.model_profile = load_model(self.config.model_profile_id)
        if self.model_profile.action_space_mode != ACTION_SPACE_MODE:
            raise ValueError(
                "Player-1 inference requires Player-1 Control; "
                f"profile {self.config.model_profile_id!r} uses "
                f"{self.model_profile.action_space_mode!r}"
            )

        game_controls = self.game.role_control.game_controls
        action_tools = build_unified_action_space_tools(
            game_controls,
            self.model_profile.action_space_mode,
        )
        self.unified_action_space_map = build_unified_action_space_map(action_tools)
        self.runtime_tool_specs = [tool.to_runtime_spec() for tool in action_tools]
        self.action_parser = PlayerOneActionParser(
            self.model_profile.action_format,
            action_space_mode=self.model_profile.action_space_mode,
            runtime_tool_specs=self.runtime_tool_specs,
        )
        validate_in_context_examples(
            self.game.require_in_context_examples(
                self.model_profile.action_space_mode, variant=self.config.in_context_example_variant
            ),
            parser=self.action_parser,
            unified_action_space_map=self.unified_action_space_map,
            admission_error=self.action_admission_error,
        )
        self.model_tools = self.action_parser.chat_template_tools()
        if not self.model_tools:
            raise ValueError(f"Model profile {self.config.model_profile_id!r} does not expose native action tools")
        fallback_payload = {
            "action_space_mode": self.model_profile.action_space_mode,
            "tool_calls": [{"tool_name": "wait", "arguments": {}}],
        }
        fallback = inspect_unified_action_output(fallback_payload, self.unified_action_space_map)
        if not fallback["is_valid"] or not isinstance(fallback["mapped_action"], Mapping):
            raise RuntimeError(f"{self.model_profile.action_space_mode} wait fallback failed canonical validation")
        self._fallback_action = dict(fallback["mapped_action"])

    def action_admission_error(self, tool_call: Mapping[str, Any] | None) -> str | None:
        """Limit the shared model tools to the catalog game's executable controls."""
        if not isinstance(tool_call, Mapping):
            return None
        controls = self.game.role_control.game_controls
        raw_calls = tool_call.get("tool_calls")
        calls = raw_calls if isinstance(raw_calls, list) else [tool_call]
        for call in calls:
            arguments = call.get("arguments") if isinstance(call, Mapping) else None
            if not isinstance(arguments, Mapping):
                continue
            for field in ("keys", "key_hold", "key_tap"):
                keys = arguments.get(field)
                if isinstance(keys, list):
                    unsupported = sorted(str(key) for key in keys if str(key) not in controls.allowed_keys)
                    if unsupported:
                        return f"unreachable_keys:{','.join(unsupported)}"
            for field, allowed in (("mouse_click", controls.mouse_click), ("mouse_hold", controls.mouse_hold)):
                button = arguments.get(field)
                if isinstance(button, str) and button not in allowed:
                    return f"unreachable_{field}:{button}"
        return None

    @property
    def action_format(self) -> str:
        return self.model_profile.action_format

    @property
    def action_space_mode(self) -> str:
        return self.model_profile.action_space_mode

    def fallback_action(self) -> dict[str, Any]:
        return dict(self._fallback_action)

    def build_initial_messages(self, task_prompt: str) -> list[dict[str, str]]:
        """Build the immutable prompt prefix for one evaluation episode.

        The system role contains only task-independent agent instructions. The
        environment, response contract, example, and task live in the first
        user message.
        """

        return render_initial_messages(
            game_rules=self.game.game_rules,
            task_prompt=task_prompt,
            role_control_block=self.game.role_control.require_role_control_block(
                self.model_profile.action_space_mode
            ),
            action_space_mode=self.model_profile.action_space_mode,
            in_context_examples=self.game.require_in_context_examples(
                self.model_profile.action_space_mode, variant=self.config.in_context_example_variant
            ),
        )

    def metadata(self) -> dict[str, Any]:
        game_controls = self.game.role_control.game_controls
        return {
            "game_id": self.config.game_id,
            "model_profile_id": self.config.model_profile_id,
            "history_context_mode": self.model_profile.history_context_mode,
            "action_format": self.action_format,
            "action_space_mode": self.action_space_mode,
            "action_duration_ms": game_controls.duration_ms,
            "allowed_keys": list(game_controls.keys),
            "mouse_click_buttons": list(game_controls.mouse_click),
            "mouse_hold_buttons": list(game_controls.mouse_hold),
            "model_tools": deepcopy(self.model_tools),
        }


__all__ = [
    "DEFAULT_MINECRAFT_GAME_ID",
    "DEFAULT_MODEL_PROFILE_ID",
    "AgentConfig",
    "GameAgent",
]
