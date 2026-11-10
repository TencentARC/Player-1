"""Shared prompt-rendering helpers for model clients."""

from __future__ import annotations

import logging
from functools import cache
from pathlib import Path
from typing import Any, Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined

LOGGER = logging.getLogger(__name__)

AGENT_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


class SemanticControlLike(Protocol):
    """Minimal shape used by prompt and semantic-control helpers."""

    action_id: str
    description: str
    binding: dict[str, Any]
    required: list[str]


@cache
def _get_env(templates_dir: str | Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(templates_dir),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_prompt_template(
    template_name: str,
    context: dict[str, Any],
    templates_dir: Path = AGENT_TEMPLATES_DIR,
) -> str:
    """Render one agent prompt template with strict Jinja variables."""
    env = _get_env(templates_dir)
    return env.get_template(template_name).render(**context).strip()


def join_prompt_sections(*sections: str | None) -> str:
    """Join non-empty prompt blocks with blank lines."""
    return "\n\n".join(
        str(section).strip()
        for section in sections
        if section and str(section).strip()
    )


def build_semantic_controls_map(
    semantic_controls: list[SemanticControlLike] | None,
) -> dict[str, dict[str, Any]]:
    """Build a semantic-control lookup keyed by canonical action id."""
    mapping: dict[str, dict[str, Any]] = {}
    for action in semantic_controls or []:
        action_id = str(getattr(action, "action_id", "") or "").strip()
        binding = getattr(action, "binding", None)
        if not action_id or not isinstance(binding, dict) or not binding:
            continue

        binding_copy = dict(binding)
        mapping[action_id] = dict(binding_copy)
    return mapping


def render_semantic_action_space(semantic_controls: list[SemanticControlLike] | None) -> str:
    """Render the semantic action block injected into general-model prompts."""
    lines = [
        "REGISTERED ACTIONS (Semantic Controls).",
        "Choose exactly ONE action per step:",
        "",
    ]

    for action in semantic_controls or []:
        action_id = str(getattr(action, "action_id", "") or "").strip()
        if not action_id:
            continue

        description = str(getattr(action, "description", "") or "").strip()
        required = [
            str(item).strip()
            for item in (getattr(action, "required", []) or [])
            if str(item).strip()
        ]

        line = f"- `{action_id}`"
        if description:
            line += f": {description}"
        if required:
            line += f" (required: {', '.join(required)})"
        lines.append(line)

    return "\n".join(lines)


def render_system_prompt(
    template_name: str,
    game_rules: str | None,
    task_prompt: str | None,
    role_section: str | None,
    computer_use_controls_section: str | None,
    semantic_action_space: str | None,
    output_format: str | None,
) -> str:
    """Render the final system prompt for one model-role pair."""
    system_prompt = render_prompt_template(
        template_name,
        {
            "game_rules_block": game_rules or "",
            "task_instruction_block": task_prompt or "",
            "role_control_block_semantic": join_prompt_sections(
                role_section,
                semantic_action_space,
            ),
            "role_control_block_computer_use": join_prompt_sections(
                role_section,
                computer_use_controls_section,
            ),
            "model_output_format_block": output_format or "",
        },
    )

    LOGGER.debug(
        "Rendered system prompt from template '%s' (%d chars)",
        template_name,
        len(system_prompt),
    )
    return system_prompt


__all__ = [
    "AGENT_TEMPLATES_DIR",
    "build_semantic_controls_map",
    "join_prompt_sections",
    "render_prompt_template",
    "render_semantic_action_space",
    "render_system_prompt",
]
