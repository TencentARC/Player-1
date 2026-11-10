"""Policy-facing observation messages for Player-1-trained models."""

from __future__ import annotations

from typing import Any

from PIL import Image

from player1.agents.prompting import DEFAULT_ACTION_PROMPT_TEXT


def build_observation_message(
    image: Image.Image,
    *,
    action_prompt_text: str = DEFAULT_ACTION_PROMPT_TEXT,
) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": action_prompt_text},
        ],
    }


__all__ = ["DEFAULT_ACTION_PROMPT_TEXT", "build_observation_message"]
