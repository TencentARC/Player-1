"""Validate that published prefixes already match the shared RL contract."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from player1.agents.actions.prompting import InContextExample
from player1.agents.prompting import GAME_AGENT_SYSTEM_PROMPT, render_initial_messages

from player1.datasets.player1_control import (
    ACTION_SPACE_MODE,
    PLAYER1_CONTROL_RESPONSE_FORMAT,
)
from player1.datasets.player1_control import (
    player1_control_model_tools as player1_control_rl_tools,
)

__all__ = ["player1_control_rl_tools", "project_player1_control_prefix"]


def project_player1_control_prefix(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Round-trip the current shared renderer without repairing stale releases."""
    if (
        len(messages) != 2
        or messages[0] != {"role": "system", "content": GAME_AGENT_SYSTEM_PROMPT}
        or messages[1].get("role") != "user"
        or not isinstance(messages[1].get("content"), str)
    ):
        raise ValueError("Player-1 Control prefix must contain the shared system and episode user message")
    prefix = messages[1]["content"]
    environment_header = "# Environment Instructions\n"
    response_marker = "\n\n# Response Format\n"
    task_marker = "\n\n# Task Instruction\n"
    if (
        not prefix.startswith(environment_header)
        or prefix.count(response_marker) != 1
        or prefix.count(task_marker) != 1
    ):
        raise ValueError("Player-1 Control prefix does not match the published section layout")
    environment, _, remainder = prefix[len(environment_header):].partition(response_marker)
    response, _, task = remainder.partition(task_marker)
    if not environment.strip() or not task.strip():
        raise ValueError("Player-1 Control prefix requires non-empty environment and task instructions")

    examples = None
    if response != PLAYER1_CONTROL_RESPONSE_FORMAT:
        example_marker = PLAYER1_CONTROL_RESPONSE_FORMAT + "\n\nResponse examples:\n"
        if not response.startswith(example_marker):
            raise ValueError("Player-1 Control prefix has an unknown release response format")
        example_text = response[len(example_marker):]
        match = re.fullmatch(r"Example 1 - ([^\n]+):\n(.+)", example_text, flags=re.DOTALL)
        if match is None:
            raise ValueError("Player-1 Control prefix has an unknown release example wrapper")
        examples = [InContextExample(name=match[1], response=match[2])]

    fields = dict(
        game_rules=environment, task_prompt=task, role_control_block=None, action_space_mode=ACTION_SPACE_MODE,
    )
    rendered = render_initial_messages(**fields, in_context_examples=examples)
    if rendered != list(messages):
        raise ValueError("Player-1 Control prefix does not round-trip the shared RL renderer")
    return rendered
