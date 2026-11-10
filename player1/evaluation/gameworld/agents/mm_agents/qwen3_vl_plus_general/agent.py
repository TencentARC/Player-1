"""Qwen3-VL Plus agent implementation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent


@dataclass
class Qwen3VLPlusConfig(BaseClientConfig):
    """Configuration for Qwen3-VL Plus."""

    model: str = "qwen3-vl-plus"
    model_type: str = "general"
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("DASHSCOPE_API_KEY")
    )
    base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class Qwen3VLPlusAgent(GeneralAgent):
    """Qwen3-VL Plus agent using DashScope's chat completions API."""

    _TOOL_CALL_PATTERN = re.compile(
        r"<tool(?:\s+|_)call>\s*(\{[\s\S]*?\})\s*</tool(?:\s+|_)call>",
        flags=re.IGNORECASE,
    )

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        api_key = self._resolve_api_key(config.api_key, env_vars=("DASHSCOPE_API_KEY",))
        self._client = OpenAI(api_key=api_key, base_url=config.base_url)
        self._model_name = config.model or "qwen3-vl-plus"

    def _parse_tool_call_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object] | None:
        name = payload.get("name")
        arguments = payload.get("arguments")
        if isinstance(arguments, str):
            arguments = self._parse_json_arguments(arguments)

        if isinstance(name, str) and name.strip():
            return {"tool_name": name.strip(), "arguments": arguments or {}}
        return None

    def _parse_tool_call_text(self, content: str) -> dict[str, object] | None:
        if not content:
            return None
        text = content.strip()

        for match in self._TOOL_CALL_PATTERN.finditer(text):
            raw = match.group(1).strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                parsed = self._parse_tool_call_payload(payload)
                if parsed:
                    return parsed

        decoder = json.JSONDecoder()
        idx = 0
        while idx < len(text):
            start = text.find("{", idx)
            if start < 0:
                break
            try:
                payload, end = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                idx = start + 1
                continue
            if isinstance(payload, dict):
                parsed = self._parse_tool_call_payload(payload)
                if parsed:
                    return parsed
            idx = start + max(1, end)
        return None

    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[object],
        tools: list[dict[str, object]],
        screenshot_path: Path,
    ) -> dict[str, object]:
        del tools
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
        request_payload: dict[str, object] = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        return request_payload

    def send_request(self, request_payload: dict[str, object]) -> object:
        return self._client.chat.completions.create(**request_payload)

    def extract_tool_call(self, response: object) -> dict[str, object] | None:
        message = self._require_choice_message(response, "Qwen")
        tool_call = None

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            first = tool_calls[0]
            function_obj = getattr(first, "function", None)
            if function_obj is None and isinstance(first, dict):
                function_obj = first.get("function")
            payload = {
                "name": getattr(function_obj, "name", None)
                if function_obj is not None and not isinstance(function_obj, dict)
                else (
                    function_obj.get("name") if isinstance(function_obj, dict) else None
                ),
                "arguments": getattr(function_obj, "arguments", None)
                if function_obj is not None and not isinstance(function_obj, dict)
                else (
                    function_obj.get("arguments")
                    if isinstance(function_obj, dict)
                    else None
                ),
            }
            tool_call = self._parse_tool_call_payload(payload)

        if not tool_call:
            tool_call = self._parse_tool_call_text(self._extract_message_text(message))
        return tool_call


__all__ = ["Qwen3VLPlusAgent", "Qwen3VLPlusConfig"]
