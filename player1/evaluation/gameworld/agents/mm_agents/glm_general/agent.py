"""GLM 4.6V agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from zai import ZaiClient

from ...harness.function_calling_utils import build_glm_action_tools
from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent


@dataclass
class GLM46VConfig(BaseClientConfig):
    """Configuration for GLM 4.6V."""

    model: str = "glm-4.6v"
    model_type: str = "general"
    api_key: str | None = field(
        default_factory=lambda: (
            os.environ.get("ZAI_API_KEY") or os.environ.get("GLM_API_KEY")
        )
    )
    base_url: str = "https://api.z.ai/api/paas/v4"
    request_timeout: float | None = 3600.0


class GLM46VAgent(GeneralAgent):
    """GLM 4.6V agent using zai-sdk chat completions."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(
            config.api_key,
            env_vars=("ZAI_API_KEY", "GLM_API_KEY"),
        )
        self._client = ZaiClient(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self._model_name = config.model

    def build_tools(self) -> list[dict[str, object]]:
        return build_glm_action_tools(self._semantic_controls_specs)

    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[object],
        tools: list[dict[str, object]],
        screenshot_path: Path,
    ) -> dict[str, object]:
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
        request_payload: dict[str, object] = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "thinking": {"type": "enabled"},
        }
        if tools:
            request_payload["tools"] = tools
            request_payload["tool_choice"] = "auto"
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        return self._client.chat.completions.create(**request_payload)

    def extract_tool_call(self, response: object) -> dict[str, object] | None:
        message = self._extract_first_choice_message(response)
        return self._extract_tool_call_from_message(message)

    def extract_reasoning(self, response: object) -> str | None:
        message = self._extract_first_choice_message(response)
        return self._extract_reasoning_content(message)


__all__ = ["GLM46VAgent", "GLM46VConfig"]
