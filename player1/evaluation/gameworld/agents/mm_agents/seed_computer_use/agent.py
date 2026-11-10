"""Seed 1.8 computer-use agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from ...harness.memory import MemoryEntry
from ..base.base_client import BaseClientConfig
from ..base.computer_use_agent import ComputerUseAgent
from ..ui_tars_common.parser import parse_ui_tars_action
from ..ui_tars_common.prompt import build_ui_tars_prompt


@dataclass
class Seed18CUAConfig(BaseClientConfig):
    """Configuration for Seed 1.8 computer use on Volcengine Ark."""

    model: str = "seed-1-8-251228"
    model_type: str = "computer_use"
    api_key: str | None = field(default_factory=lambda: os.environ.get("ARK_API_KEY"))
    base_url: str = "https://ark.ap-southeast.bytepluses.com/api/v3"
    request_timeout: float | None = 3600.0


class Seed18CUAAgent(ComputerUseAgent):
    """Seed 1.8 computer-use agent aligned with the UI-TARS format."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("ARK_API_KEY",))
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self._model = config.model or "seed-1-8-251228"

    def prepare_prompt(
        self,
        *,
        screenshot_path: Path,
        screen_width: int,
        screen_height: int,
    ) -> tuple[str | None, str, list[MemoryEntry]]:
        del screenshot_path, screen_width, screen_height
        system_prompt = build_ui_tars_prompt(
            instruction=self.config.system_prompt,
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
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        try:
            return self._client.chat.completions.create(**request_payload)
        except Exception as exc:
            raise RuntimeError(f"Seed CUA API request failed: {exc}") from exc

    def parse_response(
        self,
        response: object,
        *,
        raw_response: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[list[dict[str, object]] | None, str | None]:
        del raw_response
        message = self._require_choice_message(response, "Seed CUA")
        response_text = self._extract_message_text(message)
        self._logger.debug("Raw Seed CUA output: %s", response_text)
        action = parse_ui_tars_action(
            response_text,
            width=screen_width,
            height=screen_height,
            normalized_coordinates=True,
        )
        self._logger.debug("Seed CUA action: %s", action)
        return [action], None


__all__ = [
    "Seed18CUAAgent",
    "Seed18CUAConfig",
]
