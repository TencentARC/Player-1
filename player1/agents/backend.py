"""OpenAI-compatible model inference with inline screenshot transport."""

from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

from PIL import Image

from .backend_contract import GenerationResult, OpenAICompatibleConfig
from .chat_template import qwen_player1_prepare_messages, qwen_player1_request_chat_template_kwargs


def _wire(value):
    if isinstance(value, dict):
        if value.get("type") == "image" and isinstance(value.get("image"), Image.Image):
            buffer = io.BytesIO()
            value["image"].save(buffer, format="PNG")
            url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
            return {"type": "image_url", "image_url": {"url": url}}
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def _wire_messages(messages):
    fields = {"role", "content", "reasoning_content", "tool_calls", "tool_call_id", "name"}
    return [{key: _wire(value) for key, value in message.items() if key in fields} for message in messages]


class OpenAICompatibleBackend:
    def __init__(self, config: OpenAICompatibleConfig, *, tools):
        self.config, self.tools = config, list(tools)
        self.last_request_evidence = None

    def generate(self, messages):
        from .chat_template import qwen_player1_chat_template_contract
        prepared = qwen_player1_prepare_messages(messages, qwen_player1_chat_template_contract(self.config.model))
        payload = {
            "model": self.config.model, "messages": _wire_messages(prepared), "tools": self.tools,
            "tool_choice": self.config.tool_choice, "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature, "top_p": self.config.top_p,
            "top_k": self.config.top_k, "seed": self.config.seed,
            "chat_template_kwargs": qwen_player1_request_chat_template_kwargs(
                self.config.model, {"enable_thinking": self.config.enable_thinking},
            ),
        }
        started = time.monotonic()
        key = os.environ.get(self.config.api_key_env, "") if self.config.api_key_env else ""
        request = urllib.request.Request(
            self.config.chat_completions_url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key or 'local'}"},
        )
        for attempt in range(self.config.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                    result = json.load(response)
                break
            except urllib.error.HTTPError as error:
                transient = error.code in {408, 429} or 500 <= error.code < 600
                if not transient or attempt == self.config.max_retries:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.config.max_retries:
                    raise
            time.sleep(self.config.retry_backoff_s * 2 ** attempt)
        choice = result["choices"][0]
        message, usage = choice["message"], result.get("usage", {})
        self.last_request_evidence = {"message_count": len(messages), "model": self.config.model}
        return GenerationResult(
            text=message.get("content") or "", tool_calls=tuple(message.get("tool_calls") or ()),
            reasoning=message.get("reasoning_content") or message.get("reasoning"),
            prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason"), latency_s=time.monotonic() - started,
            request_attempts=attempt + 1,
        )


__all__ = ["GenerationResult", "OpenAICompatibleConfig", "OpenAICompatibleBackend"]
