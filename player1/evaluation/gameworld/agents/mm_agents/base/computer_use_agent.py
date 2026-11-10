"""Template flow for computer-use agents."""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Any

from .base_client import BaseClient


class ComputerUseAgent(BaseClient):
    """Shared request/response flow for low-level computer-use agents."""

    def prepare_prompt(
        self,
        *,
        screenshot_path: Path,
        screen_width: int,
        screen_height: int,
    ) -> tuple[str | None, str, list[Any]]:
        del screenshot_path, screen_width, screen_height
        return self._prepare_multimodal_prompt_and_memory()

    @abstractmethod
    def build_request_payload(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        memory_entries: list[Any],
        screenshot_path: Path,
        screen_width: int,
        screen_height: int,
    ) -> dict[str, Any]:
        """Build the provider-specific request payload."""

    @abstractmethod
    def send_request(self, request_payload: dict[str, Any]) -> Any:
        """Send the request payload to the provider."""

    @abstractmethod
    def parse_response(
        self,
        response: Any,
        *,
        raw_response: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[list[dict[str, object]] | None, str | None]:
        """Parse a provider response into candidate actions and optional reasoning."""

    def get_action(self, screenshot_path: Path) -> dict[str, object] | None:
        screen_width, screen_height = self._get_image_size(screenshot_path)
        system_prompt, user_prompt, memory_entries = self.prepare_prompt(
            screenshot_path=screenshot_path,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        request_payload = self.build_request_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_entries=memory_entries,
            screenshot_path=screenshot_path,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        raw_message_sent = self._stringify_raw_message_sent(request_payload)
        response = self.send_request(request_payload)
        raw_response = self._stringify_raw_response(response)

        reasoning: str | None = None
        error: str | None = None
        try:
            actions, reasoning = self.parse_response(
                response,
                raw_response=raw_response,
                screen_width=screen_width,
                screen_height=screen_height,
            )
            action, error = self._select_first_action(
                actions,
                raw_response=raw_response,
                error_prefix="No actions parsed",
                debug_label=self.__class__.__name__,
            )
        except Exception as exc:
            error = f"Failed to parse action: {exc}"
            self._logger.warning(error)
            action = None

        return self._complete_action(
            screenshot_path=screenshot_path,
            raw_message_sent=raw_message_sent,
            raw_response=raw_response,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_entries=memory_entries,
            action=action,
            reasoning=reasoning,
            error=error,
        )
