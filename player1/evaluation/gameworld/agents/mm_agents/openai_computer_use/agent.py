"""Computer Use Preview agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..base.base_client import BaseClientConfig
from ..base.computer_use_agent import ComputerUseAgent
from .parser import parse_openai_output_items


@dataclass
class ComputerUsePreviewConfig(BaseClientConfig):
    """Configuration for OpenAI Computer Use Preview."""

    model: str = "computer-use-preview"
    model_type: str = "computer_use"
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY")
    )


class ComputerUsePreviewAgent(ComputerUseAgent):
    """OpenAI Computer Use Preview agent using the Responses API."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("OPENAI_API_KEY",))

        from openai import OpenAI as _ResponsesAPIClient

        self._client = _ResponsesAPIClient(api_key=api_key)
        self._model_name = config.model or "computer-use-preview"

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
        request_payload = {
            "model": self._model_name,
            "tools": [
                {
                    "type": "computer_use_preview",
                    "display_width": screen_width,
                    "display_height": screen_height,
                    "environment": "browser",
                }
            ],
            "input": [],
            "reasoning": {"summary": "concise"},
            "truncation": "auto",
        }
        if system_prompt:
            request_payload["input"].append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                }
            )
        request_payload["input"].append({"role": "user", "content": input_content})
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        try:
            return self._client.responses.create(**request_payload)
        except Exception as exc:
            raise RuntimeError(f"OpenAI API call failed: {exc}") from exc

    def parse_response(
        self,
        response: object,
        *,
        raw_response: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[list[dict[str, object]] | None, str | None]:
        del raw_response, screen_width, screen_height
        return parse_openai_output_items(self._extract_response_output_items(response))


__all__ = [
    "ComputerUsePreviewAgent",
    "ComputerUsePreviewConfig",
]
