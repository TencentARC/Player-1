"""Local Qwen-VL OpenAI-compatible general agent implementation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from ..base.base_client import BaseClientConfig
from ..base.general_agent import GeneralAgent
from .parser import parse_qwen_function_tool_calls


@dataclass
class QwenLocalConfig(BaseClientConfig):
    """Configuration for Qwen-VL on a local OpenAI-compatible endpoint."""

    model: str = "Qwen2.5-VL-32B-Instruct"
    model_type: str = "general"
    endpoint: str = "http://127.0.0.1:8088/v1/chat/completions"


class QwenLocalAgent(GeneralAgent):
    """Qwen-VL agent using a local OpenAI-compatible endpoint."""

    _TOOL_CALL_PATTERN = re.compile(
        r"<tool(?:\s+|_)call>\s*(\{[\s\S]*?\})\s*</tool(?:\s+|_)call>",
        flags=re.IGNORECASE,
    )

    def __init__(self, config: BaseClientConfig, **shared_tools):
        super().__init__(config, **shared_tools)
        self._endpoint = self._require_endpoint(config.endpoint, "Qwen tools client")
        self._model = config.model

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
        response = requests.post(self._endpoint, json=request_payload, timeout=60.0)
        response.raise_for_status()
        return response

    def _stringify_raw_response(self, response_obj: object) -> str:
        return (
            response_obj.text
            if isinstance(response_obj, requests.Response)
            else super()._stringify_raw_response(response_obj)
        )

    def extract_tool_call(self, response: object) -> dict[str, object] | None:
        data = response.json() if isinstance(response, requests.Response) else response
        message = self._require_choice_message(data, "Qwen")
        tool_call = None

        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        if isinstance(tool_calls, list) and tool_calls:
            first = tool_calls[0]
            function_obj = first.get("function") if isinstance(first, dict) else None
            payload = {
                "name": function_obj.get("name")
                if isinstance(function_obj, dict)
                else None,
                "arguments": function_obj.get("arguments")
                if isinstance(function_obj, dict)
                else None,
            }
            tool_call = self._parse_tool_call_payload(payload)

        if not tool_call:
            tool_call = self._parse_tool_call_text(self._extract_message_text(message))
        return tool_call


class QwenFunctionLocalAgent(QwenLocalAgent):
    """Qwen3.5/3.6 agent using native function/parameter XML tool calls."""

    def _parse_tool_call_text(self, content: str) -> dict[str, object] | None:
        if not content:
            return None
        tool_calls = parse_qwen_function_tool_calls(content)
        if not tool_calls:
            return None
        return self._parse_tool_call_payload(tool_calls[0])


__all__ = [
    "QwenFunctionLocalAgent",
    "QwenLocalAgent",
    "QwenLocalConfig",
]
