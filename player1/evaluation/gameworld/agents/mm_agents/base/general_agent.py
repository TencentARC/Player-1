"""Template flow for semantic-control agents."""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Any

from .base_client import BaseClient


class GeneralAgent(BaseClient):
    """Shared request/response flow for semantic-control agents."""

    def prepare_prompt(
        self,
        screenshot_path: Path,
    ) -> tuple[str | None, str, list[Any]]:
        del screenshot_path
        return self._prepare_multimodal_prompt_and_memory()

    def build_tools(self) -> list[dict[str, Any]]:
        return []

    @abstractmethod
    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[Any],
        tools: list[dict[str, Any]],
        screenshot_path: Path,
    ) -> dict[str, Any]:
        """Build the provider-specific request payload."""

    @abstractmethod
    def send_request(self, request_payload: dict[str, Any]) -> Any:
        """Send the request payload to the provider."""

    @abstractmethod
    def extract_tool_call(self, response: Any) -> dict[str, object] | None:
        """Extract one semantic tool call from the provider response."""

    def extract_reasoning(self, response: Any) -> str | None:
        del response
        return None

    def extract_error(self, response: Any) -> str | None:
        del response
        return None

    def get_action(self, screenshot_path: Path) -> dict[str, object] | None:
        system_prompt, user_prompt, memory_entries = self.prepare_prompt(screenshot_path)
        tools = self.build_tools()
        request_payload = self.build_request_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_entries=memory_entries,
            tools=tools,
            screenshot_path=screenshot_path,
        )
        raw_message_sent = self._stringify_raw_message_sent(request_payload)
        response = self.send_request(request_payload)
        raw_response = self._stringify_raw_response(response)

        tool_call: dict[str, object] | None = None
        reasoning: str | None = None
        error: str | None = None
        try:
            tool_call = self.extract_tool_call(response)
            reasoning = self.extract_reasoning(response)
            error = self.extract_error(response)
        except Exception as exc:
            error = f"Failed to parse tool call: {exc}"
            self._logger.warning(error)

        return self._complete_action(
            screenshot_path=screenshot_path,
            raw_message_sent=raw_message_sent,
            raw_response=raw_response,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_entries=memory_entries,
            tool_call=tool_call,
            reasoning=reasoning,
            error=error,
        )
