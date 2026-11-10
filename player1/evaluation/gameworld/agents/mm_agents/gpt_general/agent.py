"""GPT-5.2 agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from ...harness.function_calling_utils import build_openai_action_tools
from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent


@dataclass
class GPT52Config(BaseClientConfig):
    """Configuration for GPT-5.2."""

    model: str = "gpt-5.2"
    model_type: str = "general"
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY")
    )


class GPT52Agent(GeneralAgent):
    """GPT-5.2 agent using the OpenAI Responses API."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("OPENAI_API_KEY",))
        self._client = OpenAI(api_key=api_key)
        self._model_name = config.model

    def build_tools(self) -> list[dict[str, object]]:
        return build_openai_action_tools(self._semantic_controls_specs)

    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[object],
        tools: list[dict[str, object]],
        screenshot_path: Path,
    ) -> dict[str, object]:
        input_content = self._build_user_content(
            memory_entries=memory_entries,
            append_user_text=lambda text: {"type": "input_text", "text": text},
            append_user_image=lambda image_file: {
                "type": "input_image",
                "image_url": self._build_data_url(image_file),
            },
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
        )
        request_payload: dict[str, object] = {
            "model": self._model_name,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {"role": "user", "content": input_content},
            ],
        }
        if tools:
            request_payload["tools"] = tools
            request_payload["tool_choice"] = "required"
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        return self._client.responses.create(**request_payload)

    def extract_tool_call(self, response: object) -> dict[str, object] | None:
        return self._extract_tool_call_from_output_items(
            self._extract_response_output_items(response)
        )


__all__ = ["GPT52Agent", "GPT52Config"]
