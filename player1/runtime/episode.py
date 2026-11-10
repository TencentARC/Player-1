"""Framework-neutral episode transactions for Player-1 conversations.

The controller in this module deliberately knows nothing about a concrete
model, action parser, environment, or training framework.  Those choices are
provided through :class:`EpisodePolicy`.  The controller owns only the
conversation ledger and the transaction that connects one observation,
generation proposal, verified runtime receipt, and assistant-history entry.

A turn is committed only after an ``ActionOutcome`` proves that the proposed
runtime request was executed and carries a matching runtime receipt.  Failed
validation and failed history rendering leave both the ledger and pending turn
unchanged so callers can diagnose or retry safely.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from .contracts import ActionOutcome


class EpisodeProtocolError(ValueError):
    """Raised when a policy value or action receipt violates the episode protocol."""


class EpisodeStateError(RuntimeError):
    """Raised when an operation targets an invalid or stale episode transaction."""


def _require_nonempty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpisodeProtocolError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_optional_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_nonempty_text(value, field_name=field_name)


def _require_nonnegative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EpisodeProtocolError(f"{field_name} must be a non-negative integer")
    return value


def _freeze_json(value: Any, *, path: str) -> Any:
    """Return a strict, recursively immutable JSON-compatible value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EpisodeProtocolError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EpisodeProtocolError(f"{path} contains a non-string mapping key: {key!r}")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, path=f"{path}[{index}]") for index, item in enumerate(value))
    raise EpisodeProtocolError(f"{path} contains a non-JSON value of type {type(value).__name__}")


def _freeze_json_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    frozen = _freeze_json(value, path=field_name)
    if not isinstance(frozen, Mapping):
        raise EpisodeProtocolError(f"{field_name} must be a mapping")
    return frozen


def _freeze_message_value(value: Any, *, path: str) -> Any:
    """Snapshot mutable chat containers while retaining opaque media objects.

    Image objects are intentionally treated as opaque references: importing or
    copying framework-specific media types here would violate the runtime
    dependency boundary and can duplicate large buffers.  Mutable mapping and
    sequence containers around those objects are always copied and frozen.
    """

    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EpisodeProtocolError(f"{path} contains a non-string mapping key: {key!r}")
            frozen[key] = _freeze_message_value(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_message_value(item, path=f"{path}[{index}]") for index, item in enumerate(value))
    return value


def _freeze_message(value: Any, *, field_name: str, expected_role: str | None = None) -> Mapping[str, Any]:
    frozen = _freeze_message_value(value, path=field_name)
    if not isinstance(frozen, Mapping):
        raise EpisodeProtocolError(f"{field_name} must be a mapping")
    role = _require_nonempty_text(frozen.get("role"), field_name=f"{field_name}.role")
    if expected_role is not None and role != expected_role:
        raise EpisodeProtocolError(f"{field_name}.role must be {expected_role!r}, got {role!r}")
    return frozen


def thaw_episode_value(value: Any) -> Any:
    """Detach episode containers while preserving opaque media object identity."""

    if isinstance(value, Mapping):
        return {key: thaw_episode_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw_episode_value(item) for item in value]
    return value


def _freeze_messages(values: Any, *, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EpisodeProtocolError(f"{field_name} must be a sequence of message mappings")
    return tuple(_freeze_message(message, field_name=f"{field_name}[{index}]") for index, message in enumerate(values))


def _message_image_objects(message: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return opaque image objects carried by one standard chat message."""

    content = message.get("content")
    if not isinstance(content, (tuple, list)):
        return ()
    return tuple(
        item["image"]
        for item in content
        if isinstance(item, Mapping) and item.get("type") == "image" and item.get("image") is not None
    )


def _close_image_objects(images: Sequence[Any], *, protected_ids: frozenset[int] = frozenset()) -> tuple[Any, ...]:
    """Best-effort close unprotected opaque image buffers.

    Cleanup runs only after a request or reset has otherwise succeeded, so a
    framework-specific ``close`` failure must not change episode transaction
    semantics. Objects without a close method remain ordinary opaque media.
    """

    retained: list[Any] = []
    closed_ids: set[int] = set()
    for image in images:
        image_id = id(image)
        if image_id in protected_ids:
            retained.append(image)
            continue
        try:
            close = getattr(image, "close", None)
        except Exception:  # pragma: no cover - cleanup is deliberately best effort
            retained.append(image)
            continue
        if callable(close) and image_id not in closed_ids:
            try:
                close()
            except Exception:  # pragma: no cover - cleanup is deliberately best effort
                retained.append(image)
                continue
            closed_ids.add(image_id)
    return tuple(retained)


class _ObservationImageRetention:
    """Bound live committed observation images without rewriting the ledger.

    The ledger intentionally keeps its original opaque references so history
    pairing, raw assistant text, and metadata remain unchanged. Only buffers
    outside the configured visual window are closed. Pruning happens after a
    new request is built, with every image in that request protected; this
    keeps the just-used prompt images available to downstream rollout output
    construction while bounding a long trajectory to one request window.
    """

    def __init__(self, retained_turns: int) -> None:
        self.retained_turns = _require_nonnegative_int(
            retained_turns,
            field_name="retained_observation_image_turns",
        )
        self._committed: deque[tuple[Any, ...]] = deque()

    def track_committed(self, observation_message: Mapping[str, Any]) -> None:
        self._committed.append(_message_image_objects(observation_message))

    def prune_for_request(self, messages: Sequence[Mapping[str, Any]]) -> None:
        protected_ids = frozenset(
            id(image) for message in messages for image in _message_image_objects(message)
        )
        evict_count = max(0, len(self._committed) - self.retained_turns)
        retained_evictions: list[tuple[Any, ...]] = []
        for _ in range(evict_count):
            remaining = _close_image_objects(self._committed.popleft(), protected_ids=protected_ids)
            if remaining:
                retained_evictions.append(remaining)
        self._committed.extendleft(reversed(retained_evictions))

    def release_pending(self, observation_message: Mapping[str, Any]) -> None:
        _close_image_objects(_message_image_objects(observation_message))

    def reset(self) -> None:
        images = tuple(image for turn_images in self._committed for image in turn_images)
        self._committed.clear()
        _close_image_objects(images)


def _require_action_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    action = _freeze_json_mapping(value, field_name=field_name)
    _require_nonempty_text(action.get("type"), field_name=f"{field_name}.type")
    _require_nonempty_text(action.get("id"), field_name=f"{field_name}.id")
    if "args" in action and not isinstance(action["args"], Mapping):
        raise EpisodeProtocolError(f"{field_name}.args must be a mapping when present")
    return action


@dataclass(frozen=True, slots=True)
class GenerationEnvelope:
    """Framework-neutral generated text plus optional generation metadata."""

    text: str
    reasoning: str | None = None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    finish_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise EpisodeProtocolError("generation text must be a string")
        if self.reasoning is not None and not isinstance(self.reasoning, str):
            raise EpisodeProtocolError("generation reasoning must be a string when present")
        finish_reason = _require_optional_text(self.finish_reason, field_name="generation finish_reason")
        if isinstance(self.tool_calls, (str, bytes)) or not isinstance(self.tool_calls, (tuple, list)):
            raise EpisodeProtocolError("generation tool_calls must be a sequence of mappings")
        tool_calls = tuple(
            _freeze_json_mapping(tool_call, field_name=f"generation tool_calls[{index}]")
            for index, tool_call in enumerate(self.tool_calls)
        )
        metadata = _freeze_json_mapping(self.metadata, field_name="generation metadata")
        object.__setattr__(self, "tool_calls", tool_calls)
        object.__setattr__(self, "finish_reason", finish_reason)
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True, slots=True, eq=False)
class EpisodeTurn:
    """Opaque capability identifying one pending observation turn."""


@dataclass(frozen=True, slots=True)
class EpisodeRequest:
    """Exact message context selected for one model generation request."""

    turn: EpisodeTurn
    initial_prompt_message_count: int
    messages: tuple[Mapping[str, Any], ...]
    context_info: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.turn, EpisodeTurn):
            raise EpisodeProtocolError("episode request turn must be EpisodeTurn")
        object.__setattr__(
            self,
            "initial_prompt_message_count",
            _require_nonnegative_int(
                self.initial_prompt_message_count,
                field_name="initial_prompt_message_count",
            ),
        )
        object.__setattr__(self, "messages", _freeze_messages(self.messages, field_name="request messages"))
        object.__setattr__(
            self,
            "context_info",
            _freeze_json_mapping(self.context_info, field_name="request context_info"),
        )


@dataclass(frozen=True, slots=True)
class ActionProposalDraft:
    """Policy-produced interpretation of one generation.

    ``requested_action`` is the concrete runtime request.  Invalid model output
    may carry a fallback request, but that fact must be explicit so provenance
    can be checked during commit.
    """

    decoded_output: str
    parsed_payload: Mapping[str, Any] | None
    requested_action: Mapping[str, Any]
    model_action_valid: bool
    invalid_reason: str | None = None
    fallback_used: bool = False
    fallback_tool_name: str | None = None
    action_span: tuple[int, int] | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.decoded_output, str):
            raise EpisodeProtocolError("proposal decoded_output must be a string")
        if not isinstance(self.model_action_valid, bool):
            raise EpisodeProtocolError("proposal model_action_valid must be a boolean")
        if not isinstance(self.fallback_used, bool):
            raise EpisodeProtocolError("proposal fallback_used must be a boolean")
        parsed_payload = (
            _freeze_json_mapping(self.parsed_payload, field_name="proposal parsed_payload")
            if self.parsed_payload is not None
            else None
        )
        requested_action = _require_action_mapping(
            self.requested_action,
            field_name="proposal requested_action",
        )
        invalid_reason = _require_optional_text(self.invalid_reason, field_name="proposal invalid_reason")
        fallback_tool_name = _require_optional_text(
            self.fallback_tool_name,
            field_name="proposal fallback_tool_name",
        )
        if self.model_action_valid:
            if parsed_payload is None:
                raise EpisodeProtocolError("a valid model action requires parsed_payload")
            if invalid_reason is not None:
                raise EpisodeProtocolError("a valid model action cannot carry invalid_reason")
            if self.fallback_used or fallback_tool_name is not None:
                raise EpisodeProtocolError("a valid model action cannot claim fallback provenance")
        else:
            if invalid_reason is None:
                raise EpisodeProtocolError("an invalid model action requires invalid_reason")
            if self.fallback_used and fallback_tool_name is None:
                raise EpisodeProtocolError("a fallback proposal requires fallback_tool_name")
            if not self.fallback_used and fallback_tool_name is not None:
                raise EpisodeProtocolError("fallback_tool_name requires fallback_used=True")
        action_span = self.action_span
        if action_span is not None:
            if (
                not isinstance(action_span, (tuple, list))
                or len(action_span) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) for value in action_span)
            ):
                raise EpisodeProtocolError("proposal action_span must contain exactly two integer offsets")
            start, end = action_span
            if start < 0 or end <= start or end > len(self.decoded_output):
                raise EpisodeProtocolError("proposal action_span must be within decoded_output")
            action_span = (start, end)
        evidence = _freeze_json_mapping(self.evidence, field_name="proposal evidence")
        object.__setattr__(self, "parsed_payload", parsed_payload)
        object.__setattr__(self, "requested_action", requested_action)
        object.__setattr__(self, "invalid_reason", invalid_reason)
        object.__setattr__(self, "fallback_tool_name", fallback_tool_name)
        object.__setattr__(self, "action_span", action_span)
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """One proposal for a pending request."""

    request: EpisodeRequest
    draft: ActionProposalDraft

    def __post_init__(self) -> None:
        if not isinstance(self.request, EpisodeRequest):
            raise EpisodeProtocolError("action proposal request must be EpisodeRequest")
        if not isinstance(self.draft, ActionProposalDraft):
            raise EpisodeProtocolError("action proposal draft must be ActionProposalDraft")


@runtime_checkable
class EpisodePolicy(Protocol):
    """Injected formatting and parsing behavior for :class:`EpisodeController`."""

    def build_observation_message(self, observation: Any) -> Mapping[str, Any]:
        """Convert an environment observation into one user chat message."""

    def select_context(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        initial_prompt_message_count: int,
        history_context_turns: int | None,
        history_context_old_turns: int | None = 0,
    ) -> tuple[Sequence[Mapping[str, Any]], Mapping[str, Any]]:
        """Select the exact context sent to a model and describe that selection."""

    def propose(self, generation: GenerationEnvelope) -> ActionProposalDraft:
        """Parse a generation and choose its concrete runtime request."""

    def build_assistant_message(
        self,
        proposal: ActionProposalDraft,
        outcome: ActionOutcome,
    ) -> Mapping[str, Any]:
        """Render only receipt-verified action history for a committed turn."""


@dataclass(slots=True)
class _PendingTurn:
    turn: EpisodeTurn
    observation_message: Mapping[str, Any]
    latest_request: EpisodeRequest | None = None
    latest_proposal: ActionProposal | None = None


class EpisodeController:
    """Own a receipt-gated, one-pending-turn episode message ledger."""

    def __init__(
        self,
        policy: EpisodePolicy,
        *,
        history_context_turns: int | None = 0,
        history_context_old_turns: int | None = 0,
        retained_observation_image_turns: int | None = None,
    ) -> None:
        if not isinstance(policy, EpisodePolicy):
            raise EpisodeProtocolError("policy must implement EpisodePolicy")
        if history_context_turns is not None:
            history_context_turns = _require_nonnegative_int(
                history_context_turns,
                field_name="history_context_turns",
            )
        if history_context_old_turns is not None:
            history_context_old_turns = _require_nonnegative_int(
                history_context_old_turns,
                field_name="history_context_old_turns",
            )
        image_retention = (
            None
            if retained_observation_image_turns is None
            else _ObservationImageRetention(retained_observation_image_turns)
        )
        self._policy = policy
        self._history_context_turns = history_context_turns
        self._history_context_old_turns = history_context_old_turns
        self._initialized = False
        self._initial_prompt_message_count = 0
        self._ledger: tuple[Mapping[str, Any], ...] = ()
        self._pending: _PendingTurn | None = None
        self._image_retention = image_retention

    @property
    def history_context_turns(self) -> int | None:
        return self._history_context_turns

    @property
    def history_context_old_turns(self) -> int | None:
        return self._history_context_old_turns

    @property
    def initial_prompt_message_count(self) -> int:
        return self._initial_prompt_message_count

    @property
    def ledger_messages(self) -> tuple[dict[str, Any], ...]:
        """Return a detached snapshot of all committed chat messages."""

        return tuple(thaw_episode_value(message) for message in self._ledger)

    def reset(self, initial_messages: Sequence[Mapping[str, Any]]) -> None:
        """Atomically replace episode state and invalidate all old capabilities."""

        ledger = _freeze_messages(initial_messages, field_name="initial_messages")
        if self._image_retention is not None:
            if self._pending is not None:
                self._image_retention.release_pending(self._pending.observation_message)
            self._image_retention.reset()
        self._initialized = True
        self._initial_prompt_message_count = len(ledger)
        self._ledger = ledger
        self._pending = None

    def open_turn(self, observation: Any) -> EpisodeTurn:
        """Open exactly one pending observation transaction."""

        if not self._initialized:
            raise EpisodeStateError("episode has not been reset")
        if self._pending is not None:
            raise EpisodeStateError("cannot open a turn while another turn is pending")
        observation_message = _freeze_message(
            self._policy.build_observation_message(observation),
            field_name="policy observation_message",
            expected_role="user",
        )
        turn = EpisodeTurn()
        pending = _PendingTurn(turn=turn, observation_message=observation_message)
        self._pending = pending
        return turn

    def build_request(
        self,
        turn: EpisodeTurn,
        *,
        history_context_turns_override: int | None = None,
        history_context_old_turns_override: int | None = None,
    ) -> EpisodeRequest:
        """Build the latest generation request for a pending turn.

        Passing an override is useful when a model backend reports prompt
        overflow and the caller wants to retry with fewer history turns.  A new
        request invalidates any old request and proposal for this turn.
        """

        pending = self._require_pending_turn(turn)
        if history_context_turns_override is not None:
            history_context_turns = _require_nonnegative_int(
                history_context_turns_override,
                field_name="history_context_turns_override",
            )
        else:
            history_context_turns = self._history_context_turns
        if history_context_old_turns_override is not None:
            history_context_old_turns = _require_nonnegative_int(
                history_context_old_turns_override,
                field_name="history_context_old_turns_override",
            )
        else:
            history_context_old_turns = self._history_context_old_turns
        policy_messages = [thaw_episode_value(message) for message in (*self._ledger, pending.observation_message)]
        select_context_kwargs: dict[str, Any] = {
            "initial_prompt_message_count": self._initial_prompt_message_count,
            "history_context_turns": history_context_turns,
        }
        if history_context_old_turns is None or history_context_old_turns > 0:
            select_context_kwargs["history_context_old_turns"] = history_context_old_turns
        selected = self._policy.select_context(policy_messages, **select_context_kwargs)
        if not isinstance(selected, tuple) or len(selected) != 2:
            raise EpisodeProtocolError("policy select_context must return (messages, context_info)")
        selected_messages, context_info = selected
        request = EpisodeRequest(
            turn=turn,
            initial_prompt_message_count=self._initial_prompt_message_count,
            messages=tuple(selected_messages),
            context_info=context_info,
        )
        if self._image_retention is not None:
            self._image_retention.prune_for_request(request.messages)
        pending.latest_request = request
        pending.latest_proposal = None
        return request

    def propose(self, request: EpisodeRequest, generation: GenerationEnvelope) -> ActionProposal:
        """Record a new latest proposal; later retries supersede earlier ones."""

        if not isinstance(request, EpisodeRequest):
            raise EpisodeStateError("request must be an EpisodeRequest issued by this controller")
        pending = self._require_pending_turn(request.turn)
        if request is not pending.latest_request:
            raise EpisodeStateError("request is stale or was not issued by this controller")
        if not isinstance(generation, GenerationEnvelope):
            raise EpisodeProtocolError("generation must be GenerationEnvelope")
        draft = self._policy.propose(generation)
        if not isinstance(draft, ActionProposalDraft):
            raise EpisodeProtocolError("policy propose must return ActionProposalDraft")
        proposal = ActionProposal(
            request=request,
            draft=draft,
        )
        pending.latest_proposal = proposal
        return proposal

    def commit_execution(self, proposal: ActionProposal, outcome: ActionOutcome) -> None:
        """Verify a runtime receipt and atomically append the completed turn."""

        if not isinstance(proposal, ActionProposal):
            raise EpisodeStateError("proposal must be an ActionProposal issued by this controller")
        pending = self._require_pending_turn(proposal.request.turn)
        if proposal is not pending.latest_proposal:
            raise EpisodeStateError("proposal is stale or was not issued by this controller")
        self._validate_execution_receipt(proposal.draft, outcome)
        assistant_message = _freeze_message(
            self._policy.build_assistant_message(proposal.draft, outcome),
            field_name="policy assistant_message",
            expected_role="assistant",
        )
        next_ledger = (*self._ledger, pending.observation_message, assistant_message)

        # No fallible work follows these assignments: observation and assistant
        # history become visible together or not at all.
        self._ledger = next_ledger
        self._pending = None
        if self._image_retention is not None:
            self._image_retention.track_committed(pending.observation_message)

    def _require_pending_turn(self, turn: EpisodeTurn) -> _PendingTurn:
        if not isinstance(turn, EpisodeTurn):
            raise EpisodeStateError("turn must be an EpisodeTurn issued by this controller")
        if not self._initialized:
            raise EpisodeStateError("episode has not been reset")
        pending = self._pending
        if pending is None or turn is not pending.turn:
            raise EpisodeStateError("turn is stale or was not issued by this controller")
        return pending

    @staticmethod
    def _validate_execution_receipt(draft: ActionProposalDraft, outcome: ActionOutcome) -> None:
        if not isinstance(outcome, ActionOutcome):
            raise EpisodeProtocolError("outcome must be ActionOutcome")

        admission = outcome.admission
        execution = outcome.execution
        provenance = outcome.provenance
        if execution.status != "executed":
            raise EpisodeProtocolError("episode history can commit only an executed runtime action")
        if execution.requested_action != draft.requested_action:
            raise EpisodeProtocolError("action outcome requested_action does not match the latest proposal")

        receipt = execution.executed_action
        if not isinstance(receipt, Mapping):
            raise EpisodeProtocolError("executed action requires a runtime receipt mapping")
        receipt_type = _require_nonempty_text(receipt.get("type"), field_name="executed_action.type")
        receipt_id = _require_nonempty_text(receipt.get("id"), field_name="executed_action.id")
        if "args" in receipt and not isinstance(receipt["args"], Mapping):
            raise EpisodeProtocolError("executed_action.args must be a mapping when present")
        if receipt_type != draft.requested_action.get("type") or receipt_id != draft.requested_action.get("id"):
            raise EpisodeProtocolError("executed action receipt type/id does not match the runtime request")

        if draft.model_action_valid:
            if admission.status != "accepted" or provenance.source != "model":
                raise EpisodeProtocolError("valid model action has inconsistent admission or provenance")
            if admission.model_action != draft.parsed_payload:
                raise EpisodeProtocolError("admitted model_action does not match the parsed proposal payload")
            return

        if not draft.fallback_used:
            raise EpisodeProtocolError("an invalid model action cannot commit execution without fallback provenance")
        if admission.status != "parse_rejected" or provenance.source != "fallback":
            raise EpisodeProtocolError("fallback action has inconsistent admission or provenance")
        if admission.reason != draft.invalid_reason:
            raise EpisodeProtocolError("fallback admission reason does not match the proposal")
        if admission.model_action != draft.parsed_payload:
            raise EpisodeProtocolError("rejected model_action does not match the parsed proposal payload")
        if provenance.fallback_reason != draft.invalid_reason:
            raise EpisodeProtocolError("fallback provenance reason does not match the proposal")
        requested_tool_name = draft.requested_action.get("unified_action_tool") or draft.requested_action.get("id")
        if draft.fallback_tool_name != requested_tool_name:
            raise EpisodeProtocolError("fallback tool does not match the executed runtime request")


__all__ = [
    "ActionProposal",
    "ActionProposalDraft",
    "EpisodeController",
    "EpisodePolicy",
    "EpisodeProtocolError",
    "EpisodeRequest",
    "EpisodeStateError",
    "EpisodeTurn",
    "GenerationEnvelope",
    "thaw_episode_value",
]
