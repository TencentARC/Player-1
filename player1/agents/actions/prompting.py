"""Assemble action-space-specific prompt sections from explicit catalog text."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from .parser import PlayerOneActionParser
from .runtime import inspect_unified_action_output
from .control import require_action_space_mode

PLAYER1_CONTROL_RESPONSE_FORMAT = (
    "- Give one short, concise reasoning sentence describing the relevant game state and next move, then output "
    "the action for the next game step.\n"
    "- For each game step, choose exactly one: wait, key_control, mouse_control, or key_control and mouse_control "
    "together; when both are used, they execute simultaneously.\n"
    "- Call each function at most once per game step. Do not output text between or after the function calls.\n"
    "- Use the XML function/parameter format defined by the model tool schema."
)

_ROLE_ACTION_SYNTAX_PATTERNS = (
    re.compile(r'\{\s*"name"\s*:', re.IGNORECASE),
    re.compile(r"<(?:tool_call|action)\b|<function=|<parameter=", re.IGNORECASE),
    re.compile(
        r"\b(?:control|key_control|mouse_control|wait|key|mouse_move|mouse_click|mouse_hold)\s*\(",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True, slots=True)
class InContextExample:
    """One named, complete model response used as an in-context example."""

    name: str
    response: str


def _render_role_control(role_control_block: str | None) -> str:
    """Return version-neutral catalog prose without rewriting embedded actions."""

    rendered = str(role_control_block or "").strip()
    if any(pattern.search(rendered) for pattern in _ROLE_ACTION_SYNTAX_PATTERNS):
        raise ValueError("role_control_block must use version-neutral prose without serialized action syntax")
    return rendered


def _render_in_context_examples(
    in_context_examples: Sequence[InContextExample] | None,
) -> tuple[InContextExample, ...]:
    """Validate and return ordered catalog-selected examples unchanged."""

    if in_context_examples is None:
        return ()
    if isinstance(in_context_examples, (str, bytes)):
        raise TypeError("in_context_examples must be a sequence of InContextExample objects")

    rendered = tuple(in_context_examples)
    if not rendered:
        raise ValueError("in_context_examples must contain at least one example")
    if any(not isinstance(example, InContextExample) for example in rendered):
        raise TypeError("in_context_examples must contain InContextExample objects")
    if any(not example.name.strip() or not example.response.strip() for example in rendered):
        raise ValueError("in_context_examples must contain non-empty names and responses")
    if any("\n" in example.name or example.name.strip().endswith(":") for example in rendered):
        raise ValueError("in-context example names must be single-line text without a trailing colon")
    normalized_names = [example.name.strip().casefold() for example in rendered]
    if len(set(normalized_names)) != len(normalized_names):
        raise ValueError("in-context example names must be unique")
    return rendered


def validate_in_context_examples(
    in_context_examples: Sequence[InContextExample],
    *,
    parser: PlayerOneActionParser,
    unified_action_space_map: Mapping[str, Mapping[str, Any]],
    admission_error: Callable[[Mapping[str, Any] | None], str | None] | None = None,
) -> None:
    """Require every example to parse, compile, and pass environment admission."""

    examples = _render_in_context_examples(in_context_examples)
    for index, example in enumerate(examples, start=1):
        frame = parser.parse_action_frame(example.response)
        if frame is None:
            raise ValueError(f"In-context example {index} ({example.name!r}) does not contain a valid action frame")
        inspection = inspect_unified_action_output(frame, dict(unified_action_space_map))
        if not inspection.get("is_valid"):
            reason = inspection.get("reason") or "invalid action"
            raise ValueError(f"In-context example {index} ({example.name!r}) is not executable: {reason}")
        if admission_error is not None:
            reason = admission_error(frame)
            if reason is not None:
                raise ValueError(f"In-context example {index} ({example.name!r}) is not admitted: {reason}")


def render_action_space_sections(
    *,
    role_control_block: str | None,
    action_space_mode: str,
    in_context_examples: Sequence[InContextExample] | None,
) -> dict[str, str]:
    """Assemble every action-space-specific section used by the system prompt."""

    require_action_space_mode(action_space_mode)
    rendered_examples = _render_in_context_examples(in_context_examples)
    response_sections = [PLAYER1_CONTROL_RESPONSE_FORMAT]
    if rendered_examples:
        labelled_examples = "\n\n".join(
            f"Example {index} - {example.name.strip()}:\n{example.response}"
            for index, example in enumerate(rendered_examples, start=1)
        )
        response_sections.append(f"Response examples:\n{labelled_examples}")
    return {
        "role_control_block": _render_role_control(role_control_block),
        "response_format_block": "\n\n".join(response_sections),
    }


__all__ = [
    "PLAYER1_CONTROL_RESPONSE_FORMAT",
    "InContextExample",
    "render_action_space_sections",
    "validate_in_context_examples",
]
