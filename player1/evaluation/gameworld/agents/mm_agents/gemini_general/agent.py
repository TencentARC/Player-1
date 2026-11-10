"""Gemini 3 Flash Preview agent implementation."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google import genai as google_genai
from google.genai import types as google_types

from ...harness.function_calling_utils import build_gemini_action_tools
from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent


def _use_vertex_ai_env() -> bool:
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"


@dataclass
class Gemini3FlashPreviewConfig(BaseClientConfig):
    """Configuration for Gemini 3 Flash Preview."""

    model: str = "gemini-3-flash-preview"
    model_type: str = "general"
    api_key: str | None = field(
        default_factory=lambda: (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
    )
    use_vertex_ai: bool = field(default_factory=_use_vertex_ai_env)


class Gemini3FlashPreviewAgent(GeneralAgent):
    """Gemini 3 Flash Preview agent using Google GenAI function calling."""

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        self._google_types = google_types
        if config.use_vertex_ai:
            self._client = google_genai.Client(vertexai=True)
        else:
            api_key = self._resolve_api_key(
                config.api_key,
                env_vars=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
            )
            self._client = google_genai.Client(api_key=api_key)
        self._model_name = config.model or "gemini-3-flash-preview"

    @staticmethod
    def _normalize_args(args: Any) -> dict[str, Any]:
        if args is None:
            return {}
        if isinstance(args, dict):
            return args
        try:
            return dict(args)
        except Exception:
            return {}

    @classmethod
    def _parse_tool_call(cls, parts: Iterable[object]) -> dict[str, object] | None:
        for part in parts:
            func_call = getattr(part, "function_call", None)
            if not func_call:
                continue
            name = getattr(func_call, "name", None)
            args = getattr(func_call, "args", None)
            if name:
                return {
                    "tool_name": str(name).strip(),
                    "arguments": cls._normalize_args(args),
                }
        return None

    def build_tools(self) -> list[dict[str, object]]:
        return build_gemini_action_tools(self._semantic_controls_specs)

    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[object],
        tools: list[dict[str, object]],
        screenshot_path: Path,
    ) -> dict[str, object]:
        google_types = self._google_types
        config_kwargs: dict[str, Any] = {"system_instruction": system_prompt}
        if tools:
            config_kwargs.update(
                {
                    "tools": [google_types.Tool(function_declarations=tools)],
                    "automatic_function_calling": google_types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                    "tool_config": google_types.ToolConfig(
                        function_calling_config=google_types.FunctionCallingConfig(
                            mode="ANY"
                        )
                    ),
                }
            )
        request_config = google_types.GenerateContentConfig(**config_kwargs)

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
        request_payload = {
            "model": self._model_name,
            "contents": [google_types.Content(role="user", parts=parts)],
            "config": request_config,
        }
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        return self._client.models.generate_content(**request_payload)

    def extract_tool_call(self, response: object) -> dict[str, object] | None:
        response_parts: list[object] = []
        if response.candidates and response.candidates[0].content:
            response_parts = response.candidates[0].content.parts or []
        return self._parse_tool_call(response_parts)


__all__ = [
    "Gemini3FlashPreviewAgent",
    "Gemini3FlashPreviewConfig",
]
