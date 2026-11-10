"""Player-1 action and history policy for the framework-neutral episode controller."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from player1.runtime.contracts import (
    ActionAdmission,
    ActionEffectEvidence,
    ActionExecution,
    ActionOutcome,
    ActionProvenance,
    copy_json_value,
)
from player1.runtime.episode import ActionProposal, ActionProposalDraft, GenerationEnvelope

from .actions import inspect_unified_action_output
from .actions.parser import PlayerOneActionParser
from .history_context import (
    COLLAPSED_HISTORY_CONTEXT_MODES,
    HISTORY_CONTEXT_MESSAGE_METADATA_KEY,
    build_history_context_metadata,
    canonicalize_think_action_output,
    require_history_context_mode,
    select_history_context_messages,
)

ObservationBuilder = Callable[[Any], Mapping[str, Any]]
ActionAdmissionValidator = Callable[[Mapping[str, Any] | None], str | None]

_THINK_CLOSE_PATTERN = re.compile(r"</think>", re.IGNORECASE)


def _plain_message_value(value: Any) -> Any:
    """Detach message containers while retaining opaque media objects."""

    if isinstance(value, Mapping):
        return {str(key): _plain_message_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_message_value(item) for item in value]
    return value


def build_successful_action_outcome(
    proposal: ActionProposal,
    *,
    reward: float,
    terminated: bool,
    truncated: bool,
    evidence: str = "minestudio_step_returned",
) -> ActionOutcome:
    """Build the receipt for an environment step that returned successfully."""

    draft = proposal.draft
    requested_action = copy_json_value(draft.requested_action)
    parsed_payload = None if draft.parsed_payload is None else copy_json_value(draft.parsed_payload)
    return ActionOutcome(
        admission=ActionAdmission(
            status="accepted" if draft.model_action_valid else "parse_rejected",
            reason=None if draft.model_action_valid else draft.invalid_reason,
            model_action=parsed_payload,
        ),
        execution=ActionExecution(
            status="executed",
            reason=None,
            requested_action=requested_action,
            executed_action=requested_action,
            runtime_reward=float(reward),
            environment_done=bool(terminated or truncated),
        ),
        provenance=ActionProvenance(
            source="model" if draft.model_action_valid else "fallback",
            fallback_reason=None if draft.model_action_valid else (draft.invalid_reason or "fallback_used"),
        ),
        effect=ActionEffectEvidence(status="unverifiable", evidence=(evidence,)),
    )


class PlayerOneEpisodePolicy:
    """Bind Player-1 parsing and history projection to :class:`EpisodeController`.

    The policy is shared by rollout and evaluation paths.  It accepts a fully
    reconstructed decoded model output, validates it with the common action
    parser/map, chooses the configured fallback when necessary, and renders
    only receipt-verified history after the controller commits execution.
    """

    def __init__(
        self,
        *,
        history_context_mode: str,
        history_context_old_mode: str | None = None,
        action_parser: PlayerOneActionParser,
        unified_action_space_map: Mapping[str, Mapping[str, Any]],
        fallback_action: Mapping[str, Any],
        observation_builder: ObservationBuilder,
        action_admission_validator: ActionAdmissionValidator | None = None,
    ) -> None:
        self.history_context_mode = require_history_context_mode(history_context_mode)
        self.history_context_old_mode = None
        if history_context_old_mode is not None:
            normalized_old_mode = require_history_context_mode(history_context_old_mode)
            if normalized_old_mode not in COLLAPSED_HISTORY_CONTEXT_MODES:
                expected = ", ".join(sorted(COLLAPSED_HISTORY_CONTEXT_MODES))
                raise ValueError(f"history_context_old_mode must be one of {expected}, got {normalized_old_mode!r}")
            self.history_context_old_mode = normalized_old_mode
        self.action_parser = action_parser
        self.unified_action_space_map = {
            str(key): copy_json_value(value) for key, value in unified_action_space_map.items()
        }
        self.fallback_action = copy_json_value(fallback_action)
        if not isinstance(self.fallback_action, dict):
            raise TypeError("Player-1 fallback_action must be a mapping")
        if (
            not str(self.fallback_action.get("type") or "").strip()
            or not str(self.fallback_action.get("id") or "").strip()
        ):
            raise ValueError("Player-1 fallback_action requires non-empty type and id")
        self._observation_builder = observation_builder
        self._action_admission_validator = action_admission_validator

    def build_observation_message(self, observation: Any) -> Mapping[str, Any]:
        return self._observation_builder(observation)

    def select_context(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        initial_prompt_message_count: int,
        history_context_turns: int | None,
        history_context_old_turns: int | None = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return select_history_context_messages(
            messages=[_plain_message_value(message) for message in messages],
            initial_prompt_message_count=initial_prompt_message_count,
            history_context_turns=history_context_turns,
            history_context_mode=self.history_context_mode,
            history_context_old_turns=history_context_old_turns,
            history_context_old_mode=self.history_context_old_mode,
        )

    def propose(self, generation: GenerationEnvelope) -> ActionProposalDraft:
        decoded_output = generation.text
        parsed_with_span = self.action_parser.parse_action_frame_with_span(decoded_output)
        parsed_payload = parsed_with_span[0] if parsed_with_span is not None else None
        action_span = parsed_with_span[1] if parsed_with_span is not None else None
        action_block_count = self.action_parser.count_action_blocks(decoded_output)

        format_invalid_reason = None
        if parsed_payload is None:
            format_invalid_reason = "malformed_action_block" if action_block_count else "no_valid_action"
        elif action_span is not None:
            prefix = decoded_output[: action_span[0]]
            think_close = _THINK_CLOSE_PATTERN.search(prefix)
            if think_close is not None and prefix[think_close.end() :].strip():
                format_invalid_reason = "malformed_action_block"

        inspection = inspect_unified_action_output(
            parsed_payload,
            dict(self.unified_action_space_map),
        )
        requested_action = inspection.get("mapped_action") if inspection.get("is_valid") else None
        invalid_reason = format_invalid_reason
        if requested_action is None and invalid_reason is None:
            invalid_reason = str(inspection.get("reason") or "invalid_action")

        if invalid_reason is None and requested_action is not None and self._action_admission_validator is not None:
            admission_error = self._action_admission_validator(parsed_payload)
            if admission_error is not None:
                invalid_reason = str(admission_error)
                requested_action = None
                inspection = {
                    **inspection,
                    "is_valid": False,
                    "reason": invalid_reason,
                    "invalid_kind": "out_of_environment_controls",
                    "mapped_action": None,
                }

        reached_generation_limit = bool(generation.metadata.get("reached_generation_limit", False))
        if generation.finish_reason == "length" and parsed_payload is None:
            reached_generation_limit = True
            invalid_reason = "generation_truncated"

        model_action_valid = requested_action is not None and invalid_reason is None
        fallback_used = not model_action_valid
        if fallback_used:
            requested_action = copy_json_value(self.fallback_action)
        assert isinstance(requested_action, dict)
        fallback_tool_name = None
        if fallback_used:
            fallback_tool_name = str(
                requested_action.get("unified_action_tool") or requested_action.get("id") or ""
            ).strip()

        return ActionProposalDraft(
            decoded_output=decoded_output,
            parsed_payload=parsed_payload,
            requested_action=requested_action,
            model_action_valid=model_action_valid,
            invalid_reason=None if model_action_valid else (invalid_reason or "invalid_action"),
            fallback_used=fallback_used,
            fallback_tool_name=fallback_tool_name,
            action_span=action_span,
            evidence={
                "inspection": inspection,
                "action_block_count": action_block_count,
                "reached_generation_limit": reached_generation_limit,
            },
        )

    def build_assistant_message(
        self,
        proposal: ActionProposalDraft,
        outcome: ActionOutcome,
    ) -> Mapping[str, Any]:
        """Preserve the raw PPO output and attach only trusted replay metadata."""

        del outcome  # EpisodeController has already validated all receipt axes.
        message: dict[str, Any] = {
            "role": "assistant",
            "content": proposal.decoded_output,
        }
        if proposal.model_action_valid:
            assert proposal.parsed_payload is not None
            canonical_action = self.action_parser.render_action_frame(copy_json_value(proposal.parsed_payload))
            replay_source = "admitted"
        else:
            if not proposal.fallback_tool_name:
                raise ValueError(f"{self.history_context_mode} cannot replay a fallback without its tool name")
            canonical_action = self.action_parser.render_action_call(
                {
                    "tool_name": proposal.fallback_tool_name,
                    "arguments": {},
                }
            )
            replay_source = "fallback"

        canonical_think_action = None
        if proposal.model_action_valid and proposal.action_span is not None:
            canonical_think_action = canonicalize_think_action_output(
                proposal.decoded_output,
                action_span=proposal.action_span,
                canonical_action=canonical_action,
            )
        message[HISTORY_CONTEXT_MESSAGE_METADATA_KEY] = build_history_context_metadata(
            self.history_context_mode,
            canonical_action,
            replay_source=replay_source,
            canonical_think_action=canonical_think_action,
        )
        return message


__all__ = [
    "ActionAdmissionValidator",
    "PlayerOneEpisodePolicy",
    "ObservationBuilder",
    "build_successful_action_outcome",
]
