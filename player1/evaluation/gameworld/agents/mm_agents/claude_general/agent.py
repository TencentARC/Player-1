"""Claude Sonnet 4.6 agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ...harness.function_calling_utils import build_claude_action_tools
from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent


@dataclass
class ClaudeSonnet46Config(BaseClientConfig):
    """Configuration for Claude Sonnet 4.6."""

    model: str = "claude-sonnet-4-6"
    model_type: str = "general"
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY")
    )


class ClaudeSonnet46Agent(GeneralAgent):
    """Claude Sonnet 4.6 agent using Anthropic's Messages API."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("ANTHROPIC_API_KEY",))
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model_name = config.model or "claude-sonnet-4-6"

    @staticmethod
    def _parse_tool_call(blocks: list[object] | None) -> dict[str, object] | None:
        for block in blocks or []:
            block_type = getattr(block, "type", None) or getattr(
                block, "block_type", None
            )
            if block_type != "tool_use":
                continue
            name = getattr(block, "name", None) or getattr(block, "tool_name", None)
            payload = getattr(block, "input", None)
            if name:
                return {"tool_name": str(name).strip(), "arguments": payload or {}}
        return None

    def build_tools(self) -> list[dict[str, object]]:
        return build_claude_action_tools(self._semantic_controls_specs)

    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[object],
        tools: list[dict[str, object]],
        screenshot_path: Path,
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
        request_payload: dict[str, object] = {
            "model": self._model_name,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        }
        if tools:
            request_payload["tools"] = tools
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        return self._client.messages.create(**request_payload)

    def extract_tool_call(self, response: object) -> dict[str, object] | None:
        return self._parse_tool_call(getattr(response, "content", None) or [])


__all__ = [
    "ClaudeSonnet46Agent",
    "ClaudeSonnet46Config",
]
