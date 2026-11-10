"""Render shared model-agent prompt prefixes and observation instructions."""

from __future__ import annotations

from collections.abc import Sequence

from .actions.prompting import InContextExample, render_action_space_sections

DEFAULT_ACTION_PROMPT_TEXT = "Generate the next thought and action according to the screenshot and instruction."
GAME_AGENT_SYSTEM_PROMPT = """\
You are a game agent. Your goal is to play the game to achieve the given task goal.
Observe the game screenshot to identify the game state, character, environment, and key objects.
Follow the game rules and the instructions of the task.
Act one game step at a time, using only the available keyboard/mouse tools."""


def render_action_prompt(action_prompt_text: str, *, remaining_action_turns: int | None = None) -> str:
    """Optionally expose the known action-turn budget, including the upcoming action."""

    if remaining_action_turns is None:
        return action_prompt_text
    if isinstance(remaining_action_turns, bool) or not isinstance(remaining_action_turns, int):
        raise TypeError("remaining_action_turns must be a positive integer")
    if remaining_action_turns < 1:
        raise ValueError("remaining_action_turns must be a positive integer")
    return f"{action_prompt_text}\nAction turns remaining: {remaining_action_turns} (including this turn)."


def render_initial_messages(
    *,
    game_rules: str | None,
    task_prompt: str | None,
    role_control_block: str | None,
    action_space_mode: str,
    in_context_examples: Sequence[InContextExample] | None = None,
) -> list[dict[str, str]]:
    """Render the shared system prefix and episode-specific first user message."""

    normalized_task = str(task_prompt or "").strip()
    action_sections = render_action_space_sections(
        role_control_block=role_control_block,
        action_space_mode=action_space_mode,
        in_context_examples=in_context_examples,
    )
    environment_parts = [
        str(game_rules or "").strip(),
        str(action_sections["role_control_block"] or "").strip(),
    ]
    episode_sections = [
        "# Environment Instructions\n" + "\n\n".join(part for part in environment_parts if part),
        "# Response Format\n" + str(action_sections["response_format_block"] or "").strip(),
        "# Task Instruction\n" + normalized_task,
    ]
    episode_prompt = "\n\n".join(
        section for section in episode_sections if section.split("\n", 1)[-1].strip()
    )
    return [
        {"role": "system", "content": GAME_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": episode_prompt},
    ]


__all__ = [
    "DEFAULT_ACTION_PROMPT_TEXT",
    "GAME_AGENT_SYSTEM_PROMPT",
    "render_action_prompt",
    "render_initial_messages",
]
