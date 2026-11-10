"""Common utilities shared by all model integrations."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Sequence

from PIL import Image

from ...harness.memory import (
    MemoryEntry,
    MemoryStore,
    get_memory_entries,
    parse_include_fields,
    record_memory_round,
)

LOGGER = logging.getLogger(__name__)

_BASE64_IMAGE_KEYS = frozenset(
    {
        "data",
        "base64",
        "b64",
        "b64_json",
        "image_base64",
        "image_data",
        "image_url",
        "url",
    }
)
_IMAGE_PLACEHOLDER = "<image_placeholder>"
_CIRCULAR_REF_PLACEHOLDER = "<circular_ref>"
_DEFAULT_USER_PROMPT = "Game screen:\n"


@dataclass
class BaseClientConfig:
    """Runtime configuration shared by all model clients."""

    model: str = ""
    model_type: str = "general"  # "general" | "computer_use"

    api_key: str | None = None
    endpoint: str | None = None
    system_prompt: str | None = None

    temperature: float = 0.0
    max_tokens: int = 2048
    language: str = "English"

    log_dir: str = "logs"
    log_session_id: str | None = None
    log_root: str | None = None

    enable_memory: bool = True
    memory_rounds: int = 2
    memory_format: str = "vtvtvt"
    memory_include_fields: str = "user_prompt,screenshot,reasoning,action"
    memory_screenshot_mode: str = "path"

    def with_overrides(self, **overrides: Any) -> "BaseClientConfig":
        """Return a copy with runtime overrides applied."""
        return replace(self, **overrides)


class BaseClient(ABC):
    """Abstract base class for all model-facing agents."""

    def __init__(
        self,
        config: BaseClientConfig,
        semantic_controls_specs: list[dict] | None = None,
    ) -> None:
        self.config = config
        self._logger = logging.getLogger(self.__class__.__name__)
        self._semantic_controls_specs = list(semantic_controls_specs or [])
        self._action_tool_names = {
            str(spec.get("id")).strip()
            for spec in self._semantic_controls_specs
            if isinstance(spec, dict) and spec.get("id")
        }
        self._last_interaction: dict[str, Any] | None = None
        self._memory_include_fields = parse_include_fields(config.memory_include_fields)
        self.memory_store: MemoryStore | None = None
        if config.enable_memory:
            self.memory_store = MemoryStore(capacity=config.memory_rounds)

        self._logger.info("Initialized client with model=%s", self.config.model)

    def _prepare_multimodal_prompt_and_memory(self) -> tuple[str | None, str, list[MemoryEntry]]:
        """Prepare the current prompt scaffold and relevant memory entries."""
        return self.config.system_prompt, _DEFAULT_USER_PROMPT, self._collect_memory_context()

    @staticmethod
    def _resolve_api_key(api_key: str | None, env_vars: Sequence[str]) -> str:
        if api_key:
            return api_key
        for env_var in env_vars:
            value = os.environ.get(env_var)
            if value:
                return value

        env_hint = ", ".join(env_vars) if env_vars else "api_key"
        raise ValueError(
            f"API key is required. Set one of [{env_hint}] or pass api_key in config."
        )

    @staticmethod
    def _require_endpoint(endpoint: str | None, provider_name: str) -> str:
        if endpoint:
            return endpoint
        raise ValueError(f"{provider_name} requires endpoint URL in config.")

    @staticmethod
    def _parse_json_arguments(arguments: Any) -> dict[str, Any]:
        if arguments is None:
            return {}
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _get_message_content(message: Any) -> Any:
        if isinstance(message, dict):
            return message.get("content")
        return getattr(message, "content", None)

    @classmethod
    def _extract_message_text(cls, message: Any) -> str:
        return cls._extract_text_from_content(cls._get_message_content(message)).strip()

    @staticmethod
    def _extract_first_choice_message(response: Any) -> Any | None:
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
        if not choices:
            return None

        first_choice = choices[0]
        if isinstance(first_choice, dict):
            return first_choice.get("message")
        return getattr(first_choice, "message", None)

    @classmethod
    def _require_choice_message(cls, response: Any, provider_name: str) -> Any:
        message = cls._extract_first_choice_message(response)
        if message is None:
            raise RuntimeError(f"Empty choices from {provider_name} response")
        return message

    @staticmethod
    def _extract_reasoning_content(message: Any) -> str | None:
        reasoning_content = getattr(message, "reasoning_content", None)
        if reasoning_content is None and isinstance(message, dict):
            reasoning_content = message.get("reasoning_content")

        if isinstance(reasoning_content, str):
            text = reasoning_content.strip()
            return text or None
        if isinstance(reasoning_content, list):
            parts = [str(item).strip() for item in reasoning_content if str(item).strip()]
            return "\n".join(parts) if parts else None
        return None

    @staticmethod
    def _extract_response_output_items(response: Any) -> list[Any]:
        output_items = getattr(response, "output", None)
        if output_items is None and isinstance(response, dict):
            output_items = response.get("output")
        if output_items is None and hasattr(response, "model_dump"):
            try:
                dumped = response.model_dump()  # type: ignore[attr-defined]
            except Exception:
                dumped = {}
            if isinstance(dumped, dict):
                output_items = dumped.get("output")

        if isinstance(output_items, list):
            return output_items
        if isinstance(output_items, tuple):
            return list(output_items)
        if isinstance(output_items, SequenceABC) and not isinstance(output_items, (str, bytes, bytearray)):
            return list(output_items)
        return []

    @staticmethod
    def _extract_function_name_and_arguments(data: Any) -> tuple[Any, Any]:
        if data is None:
            return None, None
        if isinstance(data, dict):
            return data.get("name"), data.get("arguments")
        return getattr(data, "name", None), getattr(data, "arguments", None)

    @classmethod
    def _extract_tool_call_from_message(cls, message: Any) -> dict[str, object] | None:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        if not tool_calls:
            return None

        for tool_call in tool_calls:
            function_obj = getattr(tool_call, "function", None)
            if function_obj is None and isinstance(tool_call, dict):
                function_obj = tool_call.get("function")

            if function_obj is not None:
                name, arguments = cls._extract_function_name_and_arguments(function_obj)
            else:
                name, arguments = cls._extract_function_name_and_arguments(tool_call)
            if not name:
                continue

            payload: dict[str, object] = {
                "tool_name": str(name).strip(),
                "arguments": cls._parse_json_arguments(arguments),
            }
            tool_call_id = getattr(tool_call, "id", None)
            if tool_call_id is None and isinstance(tool_call, dict):
                tool_call_id = tool_call.get("id")
            if tool_call_id:
                payload["tool_call_id"] = str(tool_call_id)
            return payload
        return None

    @classmethod
    def _extract_tool_call_from_output_items(
        cls,
        output_items: Sequence[Any] | None,
    ) -> dict[str, object] | None:
        for item in output_items or []:
            item_type = getattr(item, "type", None)
            if item_type is None and isinstance(item, dict):
                item_type = item.get("type")

            if item_type in {"function_call", "tool_call"}:
                name, arguments = cls._extract_function_name_and_arguments(item)
                if not name:
                    function_obj = getattr(item, "function", None)
                    if function_obj is None and isinstance(item, dict):
                        function_obj = item.get("function")
                    name, arguments = cls._extract_function_name_and_arguments(function_obj)
                if name:
                    return {
                        "tool_name": str(name).strip(),
                        "arguments": cls._parse_json_arguments(arguments),
                    }

            if item_type == "message":
                tool_call = cls._extract_tool_call_from_message(item)
                if tool_call is not None:
                    return tool_call
        return None

    def _collect_memory_context(self) -> list[MemoryEntry]:
        return get_memory_entries(
            self.memory_store,
            max_rounds=self.config.memory_rounds,
            memory_format=self.config.memory_format,
            include_fields=self._memory_include_fields,
        )

    def _build_data_url(self, image_path: Path, mime_type: str = "image/png") -> str:
        return f"data:{mime_type};base64,{self._encode_image_to_base64(image_path)}"

    def _build_user_content(
        self,
        memory_entries: list[MemoryEntry],
        append_user_text: Callable[[str], Any],
        append_user_image: Callable[[Path], Any],
        user_prompt: str | None = None,
        screenshot_path: Path | None = None,
    ) -> list[Any]:
        """Build provider-specific multimodal user content."""
        content: list[Any] = []

        self._append_memory_content(
            memory_entries=memory_entries,
            append_user_text=lambda text: content.append(append_user_text(text)),
            append_user_image=lambda image_file: content.append(append_user_image(image_file)),
            as_action_history=True,
        )
        if user_prompt is not None:
            content.append(append_user_text(user_prompt))
        if screenshot_path is not None:
            content.append(append_user_image(screenshot_path))
        return content

    @staticmethod
    def _extract_text_from_content(content: Any) -> str:
        """Flatten provider-specific text chunks into one string."""
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""

        chunks: list[str] = []
        for part in content:
            text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if isinstance(text, str) and text:
                chunks.append(text)
        return "\n".join(chunks).strip()

    def _encode_image_to_base64(self, image_path: Path) -> str:
        raw = image_path.read_bytes()
        return base64.b64encode(raw).decode("utf-8")

    def _get_image_size(self, image_path: Path) -> tuple[int, int]:
        with Image.open(image_path) as img:
            return img.size

    @abstractmethod
    def get_action(self, screenshot_path: Path) -> dict[str, object] | None:
        """Return the next action for a screenshot, or ``None`` when parsing fails."""

    @classmethod
    def _payload_to_plain_data(cls, value: Any, _seen: set[int] | None = None) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (bytes, bytearray)):
            return _IMAGE_PLACEHOLDER

        seen = _seen if _seen is not None else set()
        obj_id = id(value)
        if obj_id in seen:
            return _CIRCULAR_REF_PLACEHOLDER

        seen.add(obj_id)
        try:
            if isinstance(value, dict):
                return {str(key): cls._payload_to_plain_data(item, seen) for key, item in value.items()}
            if isinstance(value, (list, tuple, set)):
                return [cls._payload_to_plain_data(item, seen) for item in value]

            raw_dict = getattr(value, "__dict__", None)
            if isinstance(raw_dict, dict):
                return {
                    str(key): cls._payload_to_plain_data(item, seen)
                    for key, item in raw_dict.items()
                }
            return str(value)
        finally:
            seen.discard(obj_id)

    @staticmethod
    def _looks_like_data_url(text: str) -> bool:
        lower = text.lower()
        return lower.startswith("data:image/") and ";base64," in lower

    @staticmethod
    def _looks_like_base64(text: str) -> bool:
        content = (text or "").strip()
        if len(content) < 80:
            return False
        return re.fullmatch(r"[A-Za-z0-9+/=_\-\s]+", content) is not None

    @classmethod
    def _sanitize_payload_for_logging(
        cls,
        value: Any,
        parent_key: str | None = None,
    ) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for raw_key, raw_item in value.items():
                key = str(raw_key)
                key_lower = key.lower()
                if isinstance(raw_item, (bytes, bytearray)):
                    sanitized[key] = _IMAGE_PLACEHOLDER
                    continue
                if isinstance(raw_item, str):
                    if cls._looks_like_data_url(raw_item):
                        sanitized[key] = _IMAGE_PLACEHOLDER
                        continue
                    if key_lower in _BASE64_IMAGE_KEYS and cls._looks_like_base64(raw_item):
                        sanitized[key] = _IMAGE_PLACEHOLDER
                        continue
                sanitized[key] = cls._sanitize_payload_for_logging(raw_item, key_lower)
            return sanitized

        if isinstance(value, (list, tuple, set)):
            return [cls._sanitize_payload_for_logging(item, parent_key) for item in value]

        if isinstance(value, (bytes, bytearray)):
            return _IMAGE_PLACEHOLDER

        if isinstance(value, str):
            if cls._looks_like_data_url(value):
                return _IMAGE_PLACEHOLDER
            if parent_key in _BASE64_IMAGE_KEYS and cls._looks_like_base64(value):
                return _IMAGE_PLACEHOLDER
            return value

        return value

    @classmethod
    def _stringify_raw_message_sent(cls, payload_obj: Any) -> str:
        plain = cls._payload_to_plain_data(payload_obj)
        sanitized = cls._sanitize_payload_for_logging(plain)
        return json.dumps(sanitized, indent=2, ensure_ascii=False, default=str)

    @staticmethod
    def _stringify_raw_response(response_obj: Any) -> str:
        """Serialize raw provider responses for replay."""
        return str(response_obj)

    @staticmethod
    def _format_memory_text_entry(entry: MemoryEntry, *, as_action_history: bool) -> str | None:
        if entry.type != "text" or not entry.text:
            return None

        text_value = entry.text.strip()
        if not text_value:
            return None
        if not as_action_history:
            return text_value

        field = (entry.field or "").strip().lower()
        if field == "reasoning" and not text_value.lower().startswith("reasoning:"):
            text_value = f"Reasoning: {text_value}"
        elif field == "action" and not text_value.lower().startswith("action:"):
            text_value = f"Action: {text_value}"

        if not text_value.endswith("\n"):
            text_value = f"{text_value}\n"
        return text_value

    def _append_memory_content(
        self,
        memory_entries: list[MemoryEntry] | None = None,
        append_user_text: Callable[[str], None] | None = None,
        append_user_image: Callable[[Path], None] | None = None,
        as_action_history: bool = False,
    ) -> None:
        entries = list(memory_entries or [])
        if as_action_history and entries and append_user_text:
            append_user_text("## Action History\n")

        for entry in entries:
            if entry.type == "text":
                formatted_text = self._format_memory_text_entry(
                    entry,
                    as_action_history=as_action_history,
                )
                if formatted_text and append_user_text:
                    append_user_text(formatted_text)
                continue

            if entry.type == "image":
                image_file = entry.image_file()
                if image_file is None or not image_file.exists():
                    continue
                if append_user_image:
                    append_user_image(image_file)
                if entry.text and append_user_text:
                    append_user_text(entry.text)

    @staticmethod
    def _extract_action_reasoning(action: dict[str, object] | None) -> str | None:
        if not isinstance(action, dict):
            return None

        raw_reasoning = action.get("reasoning")
        if not isinstance(raw_reasoning, str):
            raw_arguments = action.get("arguments")
            if isinstance(raw_arguments, dict):
                raw_reasoning = raw_arguments.get("reasoning")

        if isinstance(raw_reasoning, str) and raw_reasoning.strip():
            return raw_reasoning.strip()
        return None

    @staticmethod
    def _serialize_action_for_memory(action: dict[str, object] | None) -> str | None:
        if action is None:
            return None
        return json.dumps(action, ensure_ascii=False, sort_keys=True, default=str)

    def _record_memory_round(
        self,
        user_prompt: str,
        screenshot_path: Path | None = None,
        action: dict[str, object] | None = None,
        reasoning: str | None = None,
    ) -> None:
        if self.memory_store is None:
            return

        record_memory_round(
            self.memory_store,
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
            action=self._serialize_action_for_memory(action),
            reasoning=reasoning or self._extract_action_reasoning(action),
        )

    def _finalize_tool_action(self, tool_call: dict[str, Any] | None) -> dict[str, Any] | None:
        if not tool_call:
            self._logger.warning("No tool call returned.")
            return None

        action = dict(tool_call)
        tool_name = str(action.get("tool_name") or "").strip()
        if not tool_name:
            self._logger.warning("Tool call missing tool_name: %s", action)
            return None

        action["tool_name"] = tool_name
        if self._action_tool_names and tool_name not in self._action_tool_names:
            self._logger.warning("Unexpected tool call: %s", tool_name)
        return action

    def _select_first_action(
        self,
        actions: Sequence[dict[str, object]] | None,
        *,
        raw_response: str,
        error_prefix: str = "No actions parsed",
        debug_label: str | None = None,
    ) -> tuple[dict[str, object] | None, str | None]:
        parsed_actions = list(actions or [])
        if not parsed_actions:
            error = f"{error_prefix}. Check raw_response: {raw_response}"
            self._logger.warning(error)
            return None, error

        action = parsed_actions[0]
        if debug_label:
            self._logger.debug("%s action: %s", debug_label, action)
        return action, None

    def _complete_action(
        self,
        *,
        screenshot_path: Path,
        raw_message_sent: str,
        raw_response: str,
        system_prompt: str | None,
        user_prompt: str | None,
        memory_entries: list[MemoryEntry] | None,
        tool_call: dict[str, Any] | None = None,
        action: dict[str, object] | None = None,
        reasoning: str | None = None,
        error: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, object] | None:
        finalized_action = action if action is not None else self._finalize_tool_action(tool_call)
        self._record_memory_round(
            user_prompt=user_prompt or "",
            screenshot_path=screenshot_path,
            action=finalized_action,
            reasoning=reasoning,
        )
        self._log_interaction(
            screenshot_path=screenshot_path,
            raw_message_sent=raw_message_sent,
            raw_response=raw_response,
            parsed_action=finalized_action,
            error=error,
            prompt=prompt,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_entries=memory_entries,
            tool_call=tool_call,
        )
        return finalized_action

    def _log_interaction(
        self,
        *,
        screenshot_path: Path,
        raw_message_sent: str = "",
        raw_response: str,
        parsed_action: dict[str, object] | None,
        error: str | None = None,
        prompt: str | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        memory_entries: list[MemoryEntry] | None = None,
        tool_call: dict[str, Any] | None = None,
    ) -> None:
        """Store the latest model interaction for runtime-level logging."""
        self._last_interaction = {
            "screenshot_path": screenshot_path,
            "prompt": prompt,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_message_sent": raw_message_sent,
            "raw_response": raw_response,
            "parsed_action": parsed_action,
            "error": error,
            "memory_entries": list(memory_entries or []),
            "model_name": self.config.model,
            "tool_call": tool_call,
        }

    def pop_logged_interaction(self) -> dict[str, Any] | None:
        """Return and clear the latest logged interaction."""
        interaction = self._last_interaction
        self._last_interaction = None
        return interaction
