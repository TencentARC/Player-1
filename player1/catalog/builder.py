"""Preset builder: combines game + task + model(s) into RuntimeConfig."""

from __future__ import annotations

from ..agents.actions import (
    build_game_control_role_controls,
    build_unified_action_space_map,
    build_unified_action_space_tools,
    validate_in_context_examples,
)
from ..agents.actions.parser import PlayerOneActionParser
from ..agents.prompting import render_initial_messages
from ..runtime.bootstrap import DEFAULT_PRESET_SPEC, configure_runtime, resolve_game_directory
from ..runtime.config import RuntimeConfig
from .games import load_game
from .models import load_model
from .tasks import load_task


def _parse_preset_parts(preset_spec: str) -> tuple[str, str, str]:
    """Parse `game_id+task_id+model` into validated parts."""
    if not isinstance(preset_spec, str) or not preset_spec.strip():
        raise ValueError("Preset spec must be a non-empty string.")

    parts = preset_spec.split("+", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid preset format: '{preset_spec}'. Expected: game_id+task_id+model")

    game_id, task_id, model_part = (part.strip() for part in parts)
    if "," in model_part:
        raise ValueError(f"Invalid preset format: '{preset_spec}'. Multiple model ids are not supported.")
    model_id = model_part.strip()
    if not game_id or not task_id or not model_id:
        raise ValueError(f"Invalid preset format: '{preset_spec}'. Expected non-empty game_id, task_id, and model.")

    return game_id, task_id, model_id


def build_runtime_config(
    preset_spec: str = DEFAULT_PRESET_SPEC, *, in_context_example_variant: str = "original"
) -> RuntimeConfig:
    """
    Build a RuntimeConfig from game + task + model specification:
    catalog syntax: game_id+task_id+model

    Args:
        preset_spec: game_id+task_id+model
        in_context_example_variant: Select original examples by default, or an explicit catalog-defined group.

    Returns:
        Complete RuntimeConfig ready for use
    """

    configure_runtime()
    game_id, task_id, model_id = _parse_preset_parts(preset_spec)
    game = load_game(game_id)
    task = load_task(game_id, task_id)
    model = load_model(model_id)
    role = game.role_control
    unified_action_tools = build_unified_action_space_tools(
        role.game_controls,
        model.action_space_mode,
    )
    role_controls = build_game_control_role_controls(role.game_controls)

    unified_action_space_map = build_unified_action_space_map(unified_action_tools)
    unified_action_space_specs = [action.to_runtime_spec() for action in unified_action_tools if action.tool_name]
    in_context_examples = game.require_in_context_examples(
        model.action_space_mode, variant=in_context_example_variant
    )
    validate_in_context_examples(
        in_context_examples,
        parser=PlayerOneActionParser(
            model.action_format,
            action_space_mode=model.action_space_mode,
            runtime_tool_specs=unified_action_space_specs,
        ),
        unified_action_space_map=unified_action_space_map,
    )

    initial_messages = render_initial_messages(
        game_rules=game.game_rules,
        task_prompt=task.task_prompt,
        role_control_block=role.require_role_control_block(model.action_space_mode),
        in_context_examples=in_context_examples,
        action_space_mode=model.action_space_mode,
    )

    config = RuntimeConfig(
        task_id=task.task_id,
        game_id=task.game_id,
        game_url_suffix=task.game_url_suffix,
        evaluator_id=task.evaluator_id,
        evaluator_config=task.evaluator_config,
        training_reward_field=task.training_reward_field,
        training_reward_scale=task.training_reward_scale,
        task_start_score_field=task.task_start_score_field,
        task_target_score_field=task.task_target_score_field,
        max_steps=task.max_steps,
        pause_during_inference=task.pause_during_inference,
        continue_on_fail=task.continue_on_fail,
        game_name=game.game_name,
        width=game.width,
        height=game.height,
        action_format=model.action_format,
        action_space_mode=model.action_space_mode,
        history_context_mode=model.history_context_mode,
        initial_messages=initial_messages,
        role_controls=role_controls,
        unified_action_space_map=unified_action_space_map,
        unified_action_space_specs=unified_action_space_specs,
    )
    config.game_name = str(resolve_game_directory(config.game_name))
    return config
