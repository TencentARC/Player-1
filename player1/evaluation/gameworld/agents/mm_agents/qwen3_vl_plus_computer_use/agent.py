"""Qwen3-VL Plus computer-use agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from ...harness.memory import MemoryEntry
from ..base.base_client import BaseClientConfig
from ..base.computer_use_agent import ComputerUseAgent
from ..qwen_common.parser import parse_qwen_tool_calls
from ..qwen_common.prompt import build_qwen_system_prompt


@dataclass
class Qwen3VLPlusCUAConfig(BaseClientConfig):
    """Configuration for remote Qwen3-VL Plus computer use."""

    model: str = "qwen3-vl-plus"
    model_type: str = "computer_use"
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("DASHSCOPE_API_KEY")
    )
    base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    request_timeout: float | None = 3600.0


class Qwen3VLPlusCUAAgent(ComputerUseAgent):
    """Qwen3-VL Plus computer-use agent using DashScope."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("DASHSCOPE_API_KEY",))
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self._model_name = config.model or "qwen3-vl-plus"

    def prepare_prompt(
        self,
        *,
        screenshot_path: Path,
        screen_width: int,
        screen_height: int,
    ) -> tuple[str | None, str, list[MemoryEntry]]:
        del screenshot_path
        system_prompt = build_qwen_system_prompt(
            screen_width=int(screen_width),
            screen_height=int(screen_height),
            instruction=self.config.system_prompt,
        )
        return system_prompt, "Game screen:\n", self._collect_memory_context()

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
        del screen_width, screen_height
        user_content = self._build_user_content(
            memory_entries=memory_entries,
            append_user_text=lambda text: {"type": "text", "text": text},
            append_user_image=lambda image_file: {
                "type": "image_url",
                "image_url": self._build_data_url(image_file),
            },
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
        )
        request_payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        try:
            return self._client.chat.completions.create(**request_payload)
        except Exception as exc:
            raise RuntimeError(f"Qwen CUA API request failed: {exc}") from exc

    def parse_response(
        self,
        response: object,
        *,
        raw_response: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[list[dict[str, object]] | None, str | None]:
        del raw_response
        message = self._require_choice_message(response, "Qwen CUA")
        response_text = self._extract_message_text(message)
        self._logger.debug("Raw Qwen CUA output: %s", response_text)
        return parse_qwen_tool_calls(
            response_text, image_w=screen_width, image_h=screen_height
        ), None


__all__ = [
    "Qwen3VLPlusCUAAgent",
    "Qwen3VLPlusCUAConfig",
]
