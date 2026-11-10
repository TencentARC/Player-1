"""Gemini 2.5 Computer Use Preview agent implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..base.base_client import BaseClientConfig
from ..base.computer_use_agent import ComputerUseAgent
from .parser import parse_gemini_function_calls


def _use_vertex_ai_env() -> bool:
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"


@dataclass
class Gemini25ComputerUsePreviewConfig(BaseClientConfig):
    """Configuration for Gemini 2.5 Computer Use Preview."""

    model: str = "gemini-2.5-computer-use-preview-10-2025"
    model_type: str = "computer_use"
    api_key: str | None = field(
        default_factory=lambda: (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
    )
    use_vertex_ai: bool = field(default_factory=_use_vertex_ai_env)


class Gemini25ComputerUsePreviewAgent(ComputerUseAgent):
    """Gemini 2.5 Computer Use Preview agent using the GenAI SDK."""

    _SUPPORTED_FUNCTIONS = (
        "open_web_browser",
        "wait_5_seconds",
        "go_back",
        "go_forward",
        "search",
        "navigate",
        "click_at",
        "hover_at",
        "type_text_at",
        "key_combination",
        "scroll_document",
        "scroll_at",
        "drag_and_drop",
    )
    _ALLOWED_FUNCTIONS = (
        "click_at",
        "type_text_at",
        "key_combination",
        "scroll_at",
        "hover_at",
        "drag_and_drop",
        "wait_5_seconds",
    )

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)

        from google import genai as google_genai
        from google.genai import types as google_types

        self._google_types = google_types
        if config.use_vertex_ai:
            self._client = google_genai.Client(vertexai=True)
        else:
            api_key = self._resolve_api_key(
                config.api_key,
                env_vars=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
            )
            self._client = google_genai.Client(api_key=api_key)
        self._model_name = config.model or "gemini-2.5-computer-use-preview-10-2025"

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
        google_types = self._google_types
        excluded = [
            name
            for name in self._SUPPORTED_FUNCTIONS
            if name not in self._ALLOWED_FUNCTIONS
        ]
        cu_tool = google_types.ComputerUse(
            environment=google_types.Environment.ENVIRONMENT_BROWSER,
            excluded_predefined_functions=excluded,
        )
        request_config = google_types.GenerateContentConfig(
            tools=[google_types.Tool(computer_use=cu_tool)],
            system_instruction=(system_prompt or None),
        )

        parts = self._build_user_content(
            memory_entries=memory_entries,
            append_user_text=lambda text: google_types.Part(text=text),
            append_user_image=lambda image_file: google_types.Part.from_bytes(
                data=image_file.read_bytes(),
                mime_type="image/png",
            ),
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
        )
        request_payload: dict[str, Any] = {
            "model": self._model_name,
            "contents": [google_types.Content(role="user", parts=parts)],
            "config": request_config,
        }
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        try:
            return self._client.models.generate_content(**request_payload)
        except Exception as exc:
            raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    def parse_response(
        self,
        response: object,
        *,
        raw_response: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[list[dict[str, object]] | None, str | None]:
        del raw_response
        response_parts: list[object] = []
        if response.candidates and response.candidates[0].content:
            response_parts = response.candidates[0].content.parts or []
        else:
            self._logger.warning(
                "Gemini returned no usable content. Full response: %s", response
            )
        return parse_gemini_function_calls(
            response_parts, image_w=screen_width, image_h=screen_height
        ), None


__all__ = [
    "Gemini25ComputerUsePreviewAgent",
    "Gemini25ComputerUsePreviewConfig",
]
