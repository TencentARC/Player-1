"""Local Qwen-VL OpenAI-compatible computer-use implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from ...harness.memory import MemoryEntry
from ..base.base_client import BaseClientConfig
from ..base.computer_use_agent import ComputerUseAgent
from .parser import parse_qwen_tool_calls
from .prompt import ToolCallFormat, build_qwen_prompt


@dataclass
class QwenLocalCUAConfig(BaseClientConfig):
    """Configuration for Qwen-VL computer use on a local endpoint."""

    model: str = "Qwen2.5-VL-32B-Instruct"
    model_type: str = "computer_use"
    endpoint: str = "http://127.0.0.1:8088/v1/chat/completions"


class QwenLocalCUAAgent(ComputerUseAgent):
    """Qwen-VL computer-use agent on a local endpoint."""

    _tool_call_format: ToolCallFormat = "json"

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        self._endpoint = self._require_endpoint(config.endpoint, "Qwen client")
        self._model = config.model or "Qwen2.5-VL-32B-Instruct"

    def prepare_prompt(
        self,
        *,
        screenshot_path: Path,
        screen_width: int,
        screen_height: int,
    ) -> tuple[str | None, str, list[MemoryEntry]]:
        del screenshot_path
        user_prompt = build_qwen_prompt(
            instruction=(
                self.config.system_prompt
                or "You are an expert game agent specialized in playing video games."
            ),
            screen_width=screen_width,
            screen_height=screen_height,
            tool_call_format=self._tool_call_format,
        )
        return None, user_prompt, self._collect_memory_context()

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
        del system_prompt, screen_width, screen_height
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
        request_payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": user_content}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        try:
            response = requests.post(self._endpoint, json=request_payload, timeout=60.0)
        except Exception as exc:
            raise RuntimeError(f"Qwen API request failed: {exc}") from exc
        if response.status_code != 200:
            raise RuntimeError(f"Qwen HTTP {response.status_code}: {response.text}")
        return response

    def _stringify_raw_response(self, response_obj: object) -> str:
        return (
            response_obj.text
            if isinstance(response_obj, requests.Response)
            else super()._stringify_raw_response(response_obj)
        )

    def parse_response(
        self,
        response: object,
        *,
        raw_response: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[list[dict[str, object]] | None, str | None]:
        del raw_response
        data = response.json() if isinstance(response, requests.Response) else response
        message = self._require_choice_message(data, "Qwen")
        response_text = self._extract_message_text(message)
        self._logger.debug("Raw Qwen output: %s", response_text)
        return self._parse_actions(
            response_text,
            screen_width=screen_width,
            screen_height=screen_height,
        ), None

    def _parse_actions(
        self,
        response_text: str,
        *,
        screen_width: int,
        screen_height: int,
    ) -> list[dict[str, object]]:
        return parse_qwen_tool_calls(
            response_text, image_w=screen_width, image_h=screen_height
        )


__all__ = [
    "QwenLocalCUAAgent",
    "QwenLocalCUAConfig",
]
