"""Preset builder: combines game + task + model(s) into RuntimeConfig."""

from __future__ import annotations

from agents.harness.prompting import build_semantic_controls_map, render_semantic_action_space, render_system_prompt
from agents.mm_agents import load_adapter, load_model
from runtime.runtime_config import RuntimeConfig

from .games import load_game
from .tasks import load_task


def _parse_preset_parts(preset_spec: str) -> tuple[str, str, list[str]]:
    """Parse `game_id+task_id+model1,model2,...` into validated parts."""
    if not isinstance(preset_spec, str) or not preset_spec.strip():
        raise ValueError("Preset spec must be a non-empty string.")

    parts = preset_spec.split("+", 2)
    if len(parts) != 3:
        raise ValueError(
            f"Invalid preset format: '{preset_spec}'. "
            "Expected: game_id+task_id+model1,model2,..."
        )

    game_id, task_id, model_part = (part.strip() for part in parts)
    models = [model.strip() for model in model_part.split(",") if model.strip()]
    if not game_id or not task_id or not models:
        raise ValueError(
            f"Invalid preset format: '{preset_spec}'. "
            "Expected non-empty game_id, task_id, and at least one model."
        )

    return game_id, task_id, models


def _resolve_model_ids(game, model_ids: list[str]) -> list[str]:
    """Expand shorthand single-model presets and validate role count."""
    resolved_model_ids = list(model_ids)
    if len(resolved_model_ids) == 1 and game.role_count > 1:
        resolved_model_ids *= game.role_count

    if len(resolved_model_ids) != game.role_count:
        raise ValueError(
            f"Game '{game.game_id}' has {game.role_count} role(s) but "
            f"{len(resolved_model_ids)} model(s) specified."
        )
    return resolved_model_ids


def build_runtime_config(preset_spec: str) -> RuntimeConfig:
    """
    Build a RuntimeConfig from game + task + model specification:
    catalog syntax: game_id+task_id+model1,model2,...

    Args:
        preset_spec: game_id+task_id+model1,model2,...

    Returns:
        Complete RuntimeConfig ready for use
    """

    game_id, task_id, model_ids = _parse_preset_parts(preset_spec)
    game = load_game(game_id)
    task = load_task(game_id, task_id)
    model_profiles = [load_model(model_id) for model_id in _resolve_model_ids(game, model_ids)]
    canonical_model_ids = [profile.model_id for profile in model_profiles]

    # Build agent configs and prompts
    role_controls_maps = []
    semantic_controls_maps = []
    semantic_controls_specs = []
    enable_memory = []
    system_prompts = []

    for role, model in zip(game.game_roles, model_profiles):
        adapter = load_adapter(model.adapter_id)
        role_controls_maps.append(role.controls.copy())

        # Build semantic controls map and specs
        semantic_controls_map = build_semantic_controls_map(role.semantic_controls)
        semantic_controls_maps.append(semantic_controls_map)
        semantic_controls_specs.append([action.to_runtime_spec() for action in role.semantic_controls])

        # Build system prompt
        semantic_action_space = render_semantic_action_space(role.semantic_controls)

        system_prompt = render_system_prompt(
            template_name=adapter.PROMPT_TEMPLATE,
            game_rules=game.game_rules,
            task_prompt=task.task_prompt,
            role_section=role.prompt.role_section,
            computer_use_controls_section=role.prompt.computer_use_controls_section,
            semantic_action_space=semantic_action_space,
            output_format=adapter.OUTPUT_FORMAT,
        )
        system_prompts.append(system_prompt)
        enable_memory.append(model.enable_memory)

    return RuntimeConfig(
        task_id=task.task_id,
        game_id=task.game_id,
        game_url_suffix=task.game_url_suffix,
        evaluator_config=task.evaluator_config,
        url=game.url,
        speed_multiplier=game.speed_multiplier,
        width=game.width,
        height=game.height,
        model_ids=canonical_model_ids,
        enable_memory=enable_memory,
        system_prompts=system_prompts,
        agent_count=game.role_count,
        role_controls_maps=role_controls_maps,
        semantic_controls_maps=semantic_controls_maps,
        semantic_controls_specs=semantic_controls_specs,
    )
