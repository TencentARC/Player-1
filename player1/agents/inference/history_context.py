"""Mode-selected history-context adapter for Player-1 models in Player-1.

This module is the Player-1 inference counterpart of the training-side
``agents.history_context`` selector. It owns only the per-trial
message ledger and assistant-history admission; prompting, generation, action
parsing, environment execution, and benchmark accounting remain outside it.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image

from player1.agents.actions.parser import PlayerOneActionParser
from player1.agents.episode_policy import PlayerOneEpisodePolicy
from player1.agents.prompting import render_action_prompt
from player1.agents.history_context import (
    require_history_context_mode,
)
from player1.runtime.contracts import ActionOutcome
from player1.runtime.episode import (
    ActionProposal,
    EpisodeController,
    EpisodeRequest,
    GenerationEnvelope,
    thaw_episode_value,
)

from player1.agents.backend import GenerationResult
from .agent import GameAgent
from .prompt import build_observation_message


@dataclass(frozen=True)
class HistoryContextRequest:
    """One request snapshot of messages selected from the trial ledger."""

    messages: list[dict[str, Any]]
    history_context_info: dict[str, Any]
    episode_request: EpisodeRequest


def _count_images(messages: list[dict[str, Any]]) -> int:
    count = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        count += sum(1 for item in content if isinstance(item, Mapping) and item.get("type") == "image")
    return count


def _normalize_native_tool_call(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    function = value.get("function")
    source = function if isinstance(function, Mapping) else value
    name = source.get("name")
    arguments = source.get("arguments")
    if isinstance(arguments, str):
        try:

            def reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                decoded: dict[str, Any] = {}
                for key, item in pairs:
                    if key in decoded:
                        raise ValueError(f"duplicate JSON member: {key}")
                    decoded[key] = item
                return decoded

            arguments = json.loads(arguments, object_pairs_hook=reject_duplicate_members)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(name, str) or not name.strip() or not isinstance(arguments, Mapping):
        return None
    return {"tool_name": name.strip(), "arguments": dict(arguments)}


def _structured_invalid_output(generation: GenerationResult) -> str:
    """Keep a deterministic raw row for strict no-backfill candidate accounting."""

    parts = [
        value
        for value in (
            str(generation.reasoning or "").strip(),
            str(generation.text or "").strip(),
        )
        if value
    ]
    parts.extend(
        json.dumps(
            tool_call,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for tool_call in generation.tool_calls
    )
    return "\n".join(parts)


def _decoded_output(
    *,
    generation: GenerationResult,
    action_parser: PlayerOneActionParser,
) -> str:
    """Reconstruct the decoded output boundary hidden by Chat Completions.

    Native Chat Completions responses split reasoning, content, and tool calls.
    For a valid structured call we append one parser-rendered canonical action.
    Content accompanying separate reasoning is retained behind an explicit
    ``</think>`` boundary so shared episode admission rejects it,
    matching the training contract that permits no text between thinking and
    the final action.
    """

    reasoning = str(generation.reasoning or "").strip()
    content = str(generation.text or "").strip()
    if not generation.tool_calls:
        return "\n".join(part for part in (reasoning, content) if part)

    native_calls = [_normalize_native_tool_call(call) for call in generation.tool_calls]
    if any(call is None for call in native_calls):
        return _structured_invalid_output(generation)
    try:
        canonical_action = action_parser.render_action_frame({
            "action_space_mode": action_parser.action_space_mode,
            "tool_calls": native_calls,
        }).strip()
    except (TypeError, ValueError):
        return _structured_invalid_output(generation)
    prefix = reasoning
    if reasoning and content:
        prefix = f"{reasoning}\n</think>\n\n{content}"
    elif content:
        prefix = content

    separator = "\n\n" if prefix else ""
    return f"{prefix}{separator}{canonical_action}"


def proposal_evidence(proposal: ActionProposal) -> dict[str, Any]:
    """Project the shared proposal into the evaluator's trace and replay fields."""

    draft = proposal.draft
    evidence = thaw_episode_value(draft.evidence)
    return {
        "model_output": draft.decoded_output,
        "tool_call": thaw_episode_value(draft.parsed_payload),
        "action": thaw_episode_value(draft.requested_action),
        "valid": draft.model_action_valid,
        "invalid_reason": draft.invalid_reason,
        "inspection": evidence["inspection"],
        "shared_episode": {
            "model_action_valid": draft.model_action_valid,
            "invalid_reason": draft.invalid_reason,
            "fallback_used": draft.fallback_used,
            "evidence": evidence,
        },
    }


class HistoryContext:
    """Player-1 facade over the shared receipt-gated episode controller."""

    def __init__(
        self,
        *,
        history_context_mode: str,
        history_context_turns: int,
        history_context_old_turns: int = 0,
        history_context_old_mode: str | None = None,
        action_prompt_text: str,
        agent: GameAgent,
        max_decisions: int | None = None,
    ) -> None:
        if (
            isinstance(history_context_turns, bool)
            or not isinstance(history_context_turns, int)
            or history_context_turns < 0
        ):
            raise ValueError("Player-1 history_context_turns must be a non-negative integer")
        resolved_mode = require_history_context_mode(history_context_mode)
        resolved_action_prompt = str(action_prompt_text)
        if max_decisions is not None:
            render_action_prompt(resolved_action_prompt, remaining_action_turns=max_decisions)
        self._completed_decisions = 0
        self._agent = agent
        self._retained_images: deque[Image.Image] = deque()
        self._retained_image_limit = history_context_turns + 1
        episode_policy = PlayerOneEpisodePolicy(
            history_context_mode=resolved_mode,
            action_parser=agent.action_parser,
            unified_action_space_map=agent.unified_action_space_map,
            fallback_action=agent.fallback_action(),
            observation_builder=lambda image: build_observation_message(
                image,
                action_prompt_text=render_action_prompt(
                    resolved_action_prompt,
                    remaining_action_turns=(
                        max_decisions - self._completed_decisions if max_decisions is not None else None
                    ),
                ),
            ),
            action_admission_validator=agent.action_admission_error,
            history_context_old_mode=history_context_old_mode,
        )
        self._controller = EpisodeController(
            episode_policy,
            history_context_turns=history_context_turns,
            history_context_old_turns=history_context_old_turns,
        )

    def reset(self, initial_messages: Sequence[Mapping[str, Any]]) -> None:
        if not initial_messages:
            raise ValueError("Player-1 history context requires non-empty initial messages")
        first = initial_messages[0]
        if not isinstance(first, Mapping) or first.get("role") != "system":
            raise ValueError("Player-1 history context initial messages must start with system")
        self._controller.reset(initial_messages)
        self._completed_decisions = 0
        while self._retained_images:
            self._retained_images.popleft().close()

    def build_request(self, image: Image.Image) -> HistoryContextRequest:
        if not self._controller.ledger_messages:
            raise RuntimeError("Reset Player-1 history context before building a request")
        turn = self._controller.open_turn(image)
        episode_request = self._controller.build_request(turn)
        self._retained_images.append(image)
        if len(self._retained_images) > self._retained_image_limit:
            self._retained_images.popleft().close()
        selected_messages = [thaw_episode_value(message) for message in episode_request.messages]
        history_context_info = dict(episode_request.context_info)
        history_context_info = {
            **history_context_info,
            "history_context_image_count": _count_images(selected_messages),
        }
        return HistoryContextRequest(
            messages=selected_messages,
            history_context_info=history_context_info,
            episode_request=episode_request,
        )

    def propose_generation(
        self,
        request: HistoryContextRequest,
        *,
        generation: GenerationResult,
    ) -> ActionProposal:
        """Convert a Chat Completions result into the shared action proposal."""

        decoded_output = _decoded_output(
            generation=generation,
            action_parser=self._agent.action_parser,
        )
        return self._controller.propose(
            request.episode_request,
            GenerationEnvelope(
                text=decoded_output,
                reasoning=generation.reasoning,
                tool_calls=tuple(generation.tool_calls),
                finish_reason=generation.finish_reason,
                metadata={
                    "prompt_tokens": generation.prompt_tokens,
                    "completion_tokens": generation.completion_tokens,
                },
            ),
        )

    def commit_execution(self, proposal: ActionProposal, outcome: ActionOutcome) -> None:
        """Commit one assistant history row only after a verified execution receipt."""

        self._controller.commit_execution(proposal, outcome)
        self._completed_decisions += 1


__all__ = [
    "HistoryContext",
    "HistoryContextRequest",
    "proposal_evidence",
]
