"""Kimi K2.5 agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from ...harness.function_calling_utils import build_kimi_action_tools
from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent


@dataclass
class KimiK25Config(BaseClientConfig):
    """Configuration for Kimi K2.5."""

    model: str = "kimi-k2.5"
    model_type: str = "general"
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("MOONSHOT_API_KEY")
    )
    base_url: str = "https://api.moonshot.ai/v1"
    request_timeout: float | None = 3600.0
    temperature: float = 1.0


class KimiK25Agent(GeneralAgent):
    """Kimi K2.5 agent using Moonshot's OpenAI-compatible chat completions API."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("MOONSHOT_API_KEY",))
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self._model_name = config.model or "kimi-k2.5"

    def build_tools(self) -> list[dict[str, object]]:
        return build_kimi_action_tools(self._semantic_controls_specs)

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
                "type": "image_url",
                "image_url": {"url": self._build_data_url(image_file)},
            },
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
        )
        request_payload: dict[str, object] = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            request_payload["tools"] = tools
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        return self._client.chat.completions.create(**request_payload)

    def extract_tool_call(self, response: object) -> dict[str, object] | None:
        message = self._extract_first_choice_message(response)
        return self._extract_tool_call_from_message(message)

    def extract_reasoning(self, response: object) -> str | None:
        message = self._extract_first_choice_message(response)
        return self._extract_reasoning_content(message)

    def extract_error(self, response: object) -> str | None:
        return (
            None
            if self._extract_first_choice_message(response) is not None
            else "Empty choices from Kimi"
        )


__all__ = ["KimiK25Agent", "KimiK25Config"]
