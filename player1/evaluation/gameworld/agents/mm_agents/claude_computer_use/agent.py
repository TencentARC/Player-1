"""Claude Sonnet 4.6 computer-use agent implementation."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from ..base.base_client import BaseClientConfig
from ..base.computer_use_agent import ComputerUseAgent
from .parser import parse_claude_tool_use_block


@dataclass
class ClaudeSonnet46CUAConfig(BaseClientConfig):
    """Configuration for Claude Sonnet 4.6 computer use."""

    model: str = "claude-sonnet-4-6"
    model_type: str = "computer_use"
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY")
    )


class ClaudeSonnet46CUAAgent(ComputerUseAgent):
    """Claude Sonnet 4.6 computer-use agent using Anthropic's beta API."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("ANTHROPIC_API_KEY",))

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model_name = config.model
        self._tool_type = "computer_20251124"
        self._beta_flag = "computer-use-2025-11-24"

    @staticmethod
    def _compute_image_scale(width: int, height: int) -> float:
        if width <= 0 or height <= 0:
            return 1.0
        long_edge = max(width, height)
        total_pixels = width * height
        long_edge_scale = 1568 / float(long_edge)
        total_pixels_scale = math.sqrt(1_150_000 / float(total_pixels))
        return min(1.0, long_edge_scale, total_pixels_scale)

    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[object],
        screenshot_path: Path,
        screen_width: int,
        screen_height: int,
    ) -> dict[str, object]:
        user_content = self._build_user_content(
            memory_entries=memory_entries,
            append_user_text=lambda text: {"type": "text", "text": text},
            append_user_image=lambda image_file: {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": self._encode_image_to_base64(image_file),
                },
            },
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
        )
        request_payload = {
            "model": self._model_name,
            "max_tokens": self.config.max_tokens,
            "tools": [
                {
                    "type": self._tool_type,
                    "name": "computer",
                    "display_width_px": int(screen_width),
                    "display_height_px": int(screen_height),
                    "display_number": 1,
                }
            ],
            "messages": [{"role": "user", "content": user_content}],
            "betas": [self._beta_flag],
        }
        if system_prompt:
            request_payload["system"] = system_prompt
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        try:
            return self._client.beta.messages.create(**request_payload)
        except Exception as exc:
            raise RuntimeError(f"Claude API call failed: {exc}") from exc

    def parse_response(
        self,
        response: object,
        *,
        raw_response: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[list[dict[str, object]] | None, str | None]:
        del raw_response
        image_scale = self._compute_image_scale(screen_width, screen_height)
        actions: list[dict[str, object]] = []
        for block in getattr(response, "content", None) or []:
            actions.extend(
                parse_claude_tool_use_block(
                    block,
                    image_w=screen_width,
                    image_h=screen_height,
                    coordinate_scale=image_scale,
                )
            )
        return actions, None


__all__ = [
    "ClaudeSonnet46CUAAgent",
    "ClaudeSonnet46CUAConfig",
]
