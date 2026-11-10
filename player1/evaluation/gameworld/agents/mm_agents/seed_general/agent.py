"""Seed 1.8 agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import OpenAI

from ...harness.function_calling_utils import build_glm_action_tools
from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent


@dataclass
class Seed18Config(BaseClientConfig):
    """Configuration for Seed 1.8 hosted on Volcengine Ark."""

    model: str = "seed-1-8-251228"
    model_type: str = "general"
    api_key: str | None = field(default_factory=lambda: os.environ.get("ARK_API_KEY"))
    base_url: str = "https://ark.ap-southeast.bytepluses.com/api/v3"
    request_timeout: float | None = 3600.0


class Seed18Agent(GeneralAgent):
    """Seed 1.8 agent using the OpenAI SDK against Ark's API."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("ARK_API_KEY",))
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self._model_name = config.model or "seed-1-8-251228"

    def build_tools(self) -> list[dict[str, object]]:
        return build_glm_action_tools(self._semantic_controls_specs)

    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[Any],
        tools: list[dict[str, Any]],
        screenshot_path: Path,
    ) -> dict[str, Any]:
        content = self._build_user_content(
            memory_entries=memory_entries,
            append_user_text=lambda text: {"type": "text", "text": text},
            append_user_image=lambda image_file: {
                "type": "image_url",
                "image_url": {"url": self._build_data_url(image_file)},
            },
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
        )
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": content},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

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
            else "Empty choices from Seed"
        )


__all__ = ["Seed18Agent", "Seed18Config"]
