"""UI-TARS 1.5 agent implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from ...harness.memory import MemoryEntry
from ..base.base_client import BaseClientConfig
from ..base.computer_use_agent import ComputerUseAgent
from ..ui_tars_common.parser import parse_ui_tars_action
from ..ui_tars_common.prompt import build_ui_tars_prompt


@dataclass
class UITars15Config(BaseClientConfig):
    """Configuration for UI-TARS 1.5 7B."""

    model: str = "ByteDance-Seed/UI-TARS-1.5-7B"
    model_type: str = "computer_use"
    endpoint: str = "http://127.0.0.1:8004/v1/chat/completions"


class UITars15Agent(ComputerUseAgent):
    """UI-TARS 1.5 7B agent using an OpenAI-compatible endpoint."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        self._endpoint = self._require_endpoint(config.endpoint, "UI-TARS client")
        self._model = config.model or "UI-TARS-1.5-7B"

    def prepare_prompt(
        self,
        *,
        screenshot_path: Path,
        screen_width: int,
        screen_height: int,
    ) -> tuple[str | None, str, list[MemoryEntry]]:
        del screenshot_path, screen_width, screen_height
        system_prompt = build_ui_tars_prompt(
            instruction=self.config.system_prompt or "",
            language=self.config.language,
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
                "image_url": {"url": self._build_data_url(image_file)},
            },
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
        )
        request_payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "top_p": None,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        try:
            response = requests.post(self._endpoint, json=request_payload, timeout=60.0)
        except Exception as exc:
            raise RuntimeError(f"UI-TARS API request failed: {exc}") from exc
        if response.status_code != 200:
            raise RuntimeError(f"UI-TARS HTTP {response.status_code}: {response.text}")
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
        message = self._require_choice_message(data, "UI-TARS")
        response_text = self._extract_message_text(message)
        self._logger.debug("Raw UI-TARS output: %s", response_text)
        action = parse_ui_tars_action(
            response_text, width=screen_width, height=screen_height
        )
        self._logger.debug("UI-TARS action: %s", action)
        return [action], None


__all__ = ["UITars15Agent", "UITars15Config"]
