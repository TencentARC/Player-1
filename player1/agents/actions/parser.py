"""Strict action-format parsing for Player-1 agent responses."""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .control import player1_control_tool_calls, normalize_player1_control_frame
from .serialization import render_action_payload as render_canonical_action_payload
from .serialization import require_action_format
from .tools import build_model_action_tools
from .control import ACTION_SPACE_MODE, require_action_space_mode

TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"<tool_call\b[\s\S]*?</tool_call>",
    re.IGNORECASE,
)
QWEN3_CODER_XML_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*<function=(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)>"
    r"(?P<body>[\s\S]*?)</function>\s*</tool_call>",
    re.IGNORECASE,
)
QWEN3_CODER_XML_PARAMETER_PATTERN = re.compile(
    r"<parameter=(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)>"
    r"(?P<value>[\s\S]*?)</parameter>",
    re.IGNORECASE,
)


class _DuplicateJSONObjectMemberError(ValueError):
    """Raised when strict JSON decoding observes the same object member twice."""


def find_action_block_spans(
    text: str,
    action_block_pattern: re.Pattern[str],
    *,
    end: int | None = None,
) -> list[tuple[int, int]]:
    """Return action-block character spans without depending on training code."""

    if not text:
        return []
    limit = len(text) if end is None else max(0, min(len(text), end))
    return [match.span() for match in action_block_pattern.finditer(text[:limit])]


def count_action_blocks(text: str, action_block_pattern: re.Pattern[str], *, end: int | None = None) -> int:
    """Count action blocks in the requested text prefix."""

    return len(find_action_block_spans(text, action_block_pattern, end=end))


def _reject_duplicate_json_object_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for name, value in pairs:
        if name in decoded:
            raise _DuplicateJSONObjectMemberError(name)
        decoded[name] = value
    return decoded


def _decode_qwen_parameter(
    value: str,
    *,
    reject_duplicate_json_object_members: bool = False,
) -> Any:
    stripped = value.strip()
    try:
        if reject_duplicate_json_object_members:
            return json.loads(
                stripped,
                object_pairs_hook=_reject_duplicate_json_object_members,
            )
        return json.loads(stripped)
    except json.JSONDecodeError:
        return stripped


def _parse_qwen3_coder_xml_action(
    action_block: str,
    *,
    reject_duplicate_json_object_members: bool = False,
) -> dict[str, Any] | None:
    match = QWEN3_CODER_XML_TOOL_CALL_PATTERN.fullmatch(action_block)
    if match is None:
        return None

    body = match.group("body")
    arguments: dict[str, Any] = {}
    cursor = 0
    for parameter_match in QWEN3_CODER_XML_PARAMETER_PATTERN.finditer(body):
        if body[cursor : parameter_match.start()].strip():
            return None
        parameter_name = parameter_match.group("name")
        if parameter_name in arguments:
            return None
        try:
            arguments[parameter_name] = _decode_qwen_parameter(
                parameter_match.group("value"),
                reject_duplicate_json_object_members=reject_duplicate_json_object_members,
            )
        except _DuplicateJSONObjectMemberError:
            return None
        cursor = parameter_match.end()
    if body[cursor:].strip():
        return None
    return {
        "tool_name": match.group("name"),
        "arguments": arguments,
    }


class PlayerOneActionParser:
    """Parse and mask the configured serialization and action-space protocol."""

    def __init__(
        self,
        action_format: str,
        *,
        action_space_mode: str = ACTION_SPACE_MODE,
        runtime_tool_specs: Sequence[Mapping[str, Any]] | None = None,
    ):
        self.action_format = require_action_format(action_format)
        self.action_space_mode = require_action_space_mode(action_space_mode)
        self.runtime_tool_specs = list(runtime_tool_specs or [])
        self.action_block_pattern = TOOL_CALL_BLOCK_PATTERN

    def chat_template_tools(self) -> list[dict[str, Any]]:
        return build_model_action_tools(self.runtime_tool_specs)

    def _parse_action_block(self, action_block: str) -> dict[str, Any] | None:
        return _parse_qwen3_coder_xml_action(
            action_block,
            reject_duplicate_json_object_members=True,
        )

    def _tool_argument_order(self, tool_name: str) -> tuple[str, ...]:
        for spec in self.runtime_tool_specs:
            if str(spec.get("id") or "").strip() != tool_name:
                continue
            argument_schema = spec.get("argument_schema")
            if not isinstance(argument_schema, Mapping):
                return ()
            properties = argument_schema.get("properties")
            if not isinstance(properties, Mapping):
                return ()
            return tuple(str(name) for name in properties)
        return ()

    def _parse_control_frame(
        self,
        text: str,
        action_spans: list[tuple[int, int]],
    ) -> tuple[dict[str, Any], tuple[int, int]] | None:
        """Parse one Control frame from one or two adjacent device calls."""

        if len(action_spans) > 2 or any(
            text[left[1] : right[0]].strip() for left, right in itertools.pairwise(action_spans)
        ):
            return None
        payloads = [self._parse_action_block(text[start:end]) for start, end in action_spans]
        if any(payload is None for payload in payloads):
            return None
        normalized_payloads = [payload for payload in payloads if payload is not None]
        frame = normalize_player1_control_frame(normalized_payloads)
        if frame is None:
            return None
        return frame, (action_spans[0][0], action_spans[-1][1])

    def _parse_frame_with_span(self, text: str) -> tuple[dict[str, Any], tuple[int, int]] | None:
        action_spans = self.find_action_block_spans(text)
        if not action_spans or text[action_spans[-1][1] :].strip():
            return None

        return self._parse_control_frame(text, action_spans)

    def parse_action_frame(self, text: str) -> dict[str, Any] | None:
        """Return the canonical action frame for one policy turn."""

        parsed = self._parse_frame_with_span(text)
        return parsed[0] if parsed is not None else None

    def parse_action_frame_with_span(
        self,
        text: str,
    ) -> tuple[dict[str, Any], tuple[int, int]] | None:
        """Return one canonical frame and its complete source span."""

        return self._parse_frame_with_span(text)

    def _render_single_action_payload(self, payload: Mapping[str, Any]) -> str:
        tool_name = payload.get("tool_name")
        argument_order = self._tool_argument_order(tool_name) if isinstance(tool_name, str) else ()
        return render_canonical_action_payload(
            self.action_format,
            payload,
            argument_order=argument_order,
        )

    def render_action_frame(self, frame: Mapping[str, Any]) -> str:
        """Render one canonical frame in the configured format."""

        tool_calls = player1_control_tool_calls(frame)
        if tool_calls is None:
            raise ValueError(f"{self.action_space_mode} rendering requires a valid frame envelope")
        return "\n".join(self._render_single_action_payload(call) for call in tool_calls)

    def render_action_call(self, payload: Mapping[str, Any]) -> str:
        """Render exactly one tool call using the Control XML codec."""

        return self._render_single_action_payload(payload)

    def find_selected_action_span(self, text: str) -> tuple[int, int] | None:
        parsed = self._parse_frame_with_span(text)
        return parsed[1] if parsed is not None else None

    def find_action_block_spans(self, text: str, *, end: int | None = None) -> list[tuple[int, int]]:
        return find_action_block_spans(text, self.action_block_pattern, end=end)

    def count_action_blocks(self, text: str, *, end: int | None = None) -> int:
        return count_action_blocks(text, self.action_block_pattern, end=end)


__all__ = [
    "PlayerOneActionParser",
    "count_action_blocks",
    "find_action_block_spans",
    "require_action_format",
]
