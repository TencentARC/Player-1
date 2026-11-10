"""Shared model prompts with strict 200 ms recorded-action validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from player1.agents.actions.control import ACTION_SPACE_MODE
from player1.agents.actions.control import validate_cross_arguments as runtime_cross_argument_errors
from player1.agents.actions.prompting import PLAYER1_CONTROL_RESPONSE_FORMAT, InContextExample
from player1.agents.actions.tools import build_model_action_tools, build_unified_action_space_tools
from player1.agents.prompting import render_initial_messages as render_runtime_initial_messages
from player1.runtime.types import GameControls

PLAYER1_CONTROL_MODEL_TOOLS_SCHEMA = "player1.action.tools"
PLAYER1_CONTROL_COORDINATE_SYSTEM = "normalized_viewport_plane"
PLAYER1_CONTROL_CADENCE_PROFILE_ID = "decision_200ms"
PLAYER1_CONTROL_DURATION_MS = 200
PLAYER1_CONTROL_ABSOLUTE_MIN = 0
PLAYER1_CONTROL_ABSOLUTE_MAX = 1000
PLAYER1_CONTROL_RELATIVE_MIN = -1000
PLAYER1_CONTROL_RELATIVE_MAX = 1000


def player1_control_runtime_tools() -> list[dict[str, Any]]:
    """Keep key enums and execution constraints outside the model-facing schema."""
    return [
        spec.to_runtime_spec()
        for spec in build_unified_action_space_tools(
            GameControls(duration_ms=PLAYER1_CONTROL_DURATION_MS),
            ACTION_SPACE_MODE,
        )
    ]


def player1_control_model_tools() -> list[dict[str, Any]]:
    """Use exactly the current RL tool text, property order and compact schema."""
    return build_model_action_tools(player1_control_runtime_tools())


def validate_player1_control_arguments(arguments_by_tool: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Apply runtime conflicts plus the release's exact-integer pointer rule."""

    errors = runtime_cross_argument_errors(arguments_by_tool)
    move = arguments_by_tool.get("mouse_control", {}).get("mouse_move")
    if isinstance(move, Mapping):
        mode = move.get("mode")
        axes = ("x", "y") if mode == "absolute" else ("dx", "dy") if mode == "relative" else ()
        for axis in axes:
            if isinstance(move.get(axis), bool) or not isinstance(move.get(axis), int):
                errors.append(
                    {
                        "code": "oneOf",
                        "path": ["mouse_control", "mouse_move", axis],
                        "message": f"{axis} must be an exact integer viewport coordinate",
                    }
                )
        if mode == "relative" and move.get("dx") == 0 and move.get("dy") == 0:
            errors.append(
                {
                    "code": "zero_relative_pointer",
                    "path": ["mouse_control", "mouse_move"],
                    "message": "an exact zero relative displacement must omit mouse_move",
                }
            )
    return errors


def render_initial_messages(
    *,
    game_rules: str | None,
    task_prompt: str | None,
    role_control_block: str | None,
    action_space_mode: str,
    in_context_example: InContextExample | None = None,
) -> list[dict[str, str]]:
    """Render the trajectory-selected example through the shared RL renderer."""
    if action_space_mode != ACTION_SPACE_MODE:
        raise ValueError(f"SFT requires action_space_mode={ACTION_SPACE_MODE!r}")
    return render_runtime_initial_messages(
        game_rules=game_rules,
        task_prompt=task_prompt,
        role_control_block=role_control_block,
        action_space_mode=action_space_mode,
        in_context_examples=None if in_context_example is None else [in_context_example],
    )


__all__ = [
    "ACTION_SPACE_MODE",
    "PLAYER1_CONTROL_ABSOLUTE_MAX",
    "PLAYER1_CONTROL_ABSOLUTE_MIN",
    "PLAYER1_CONTROL_CADENCE_PROFILE_ID",
    "PLAYER1_CONTROL_COORDINATE_SYSTEM",
    "PLAYER1_CONTROL_DURATION_MS",
    "PLAYER1_CONTROL_MODEL_TOOLS_SCHEMA",
    "PLAYER1_CONTROL_RELATIVE_MAX",
    "PLAYER1_CONTROL_RELATIVE_MIN",
    "PLAYER1_CONTROL_RESPONSE_FORMAT",
    "player1_control_model_tools",
    "player1_control_runtime_tools",
    "render_initial_messages",
    "validate_player1_control_arguments",
]
