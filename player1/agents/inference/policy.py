"""Player-1 inference through the shared episode controller."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Protocol

from PIL import Image

from player1.agents.chat_template import qwen_player1_chat_template_contract
from player1.agents.episode_policy import build_successful_action_outcome
from player1.runtime.episode import ActionProposal, thaw_episode_value

from player1.agents.backend import (
    GenerationResult,
    OpenAICompatibleBackend,
    OpenAICompatibleConfig,
)
from player1.agents.inference.contracts import (
    EnvironmentStep,
    PolicyStep,
)
from .agent import GameAgent
from .history_context import HistoryContext, proposal_evidence
from .prompt import DEFAULT_ACTION_PROMPT_TEXT

QWEN35_ACTION_MAX_TOKENS = 512
DEFAULT_QWEN35_ACTION_FORMAT_RETRY_MAX = 1


class _MessageBackend(Protocol):
    last_request_evidence: Mapping[str, Any] | None

    def generate(self, messages: Sequence[Mapping[str, Any]]) -> GenerationResult: ...


QwenBackendFactory = Callable[
    [OpenAICompatibleConfig, Sequence[Mapping[str, Any]]],
    _MessageBackend,
]


@dataclass(frozen=True)
class _PendingHistoryContextCommit:
    policy_step: PolicyStep
    proposal: ActionProposal


def _default_qwen_backend(
    config: OpenAICompatibleConfig,
    tools: Sequence[Mapping[str, Any]],
) -> OpenAICompatibleBackend:
    return OpenAICompatibleBackend(config, tools=tools)


def _validated_instruction_seed(
    instruction: str,
    seed: int,
    context: Mapping[str, Any] | None,
) -> tuple[str, int, dict[str, Any]]:
    normalized_instruction = str(instruction or "").strip()
    if not normalized_instruction:
        raise ValueError("Player-1 policy instruction cannot be empty")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("Player-1 policy seed must be an integer")
    if context is not None and not isinstance(context, Mapping):
        raise TypeError("Player-1 policy context must be a mapping")
    return normalized_instruction, seed, deepcopy(dict(context or {}))


def _rgb_copy(image: Image.Image) -> Image.Image:
    if not isinstance(image, Image.Image):
        raise TypeError(f"Player-1 policy observation must be PIL.Image, got {type(image)!r}")
    return image.convert("RGB").copy()


def _transport_evidence(backend: object) -> dict[str, Any] | None:
    evidence = getattr(backend, "last_request_evidence", None)
    return deepcopy(dict(evidence)) if isinstance(evidence, Mapping) else None


def _contains_image(message: Mapping[str, Any]) -> bool:
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(item, Mapping) and item.get("type") == "image" for item in content
    )


def _input_image_references(
    messages: Sequence[Mapping[str, Any]],
    *,
    initial_prompt_message_count: int,
    history_context_info: Mapping[str, Any],
) -> list[dict[str, Any]]:
    retained_indices = history_context_info.get("retained_history_context_indices")
    total_turns = history_context_info.get("total_history_context_turns")
    if not isinstance(retained_indices, (list, tuple)) or not isinstance(total_turns, int):
        return []
    history_messages = messages[initial_prompt_message_count:-1]
    history_users = [message for message in history_messages if message.get("role") == "user"]
    if len(history_users) != len(retained_indices):
        raise RuntimeError("Player-1 history image references do not match the selected history turns")
    old_count = int(history_context_info.get("retained_old_history_context_turns", 0))
    references = [
        {
            "layer": "old" if position < old_count else "recent",
            "source_decision": int(turn_index) + 1,
        }
        for position, (turn_index, message) in enumerate(zip(retained_indices, history_users, strict=True))
        if _contains_image(message)
    ]
    if messages and _contains_image(messages[-1]):
        references.append({"layer": "current", "source_decision": total_turns + 1})
    return references


def _qwen_history_context(context: Mapping[str, Any]) -> tuple[int, int, str | None, str]:
    history_context_turns = context.get("history_context_turns", 0)
    if (
        isinstance(history_context_turns, bool)
        or not isinstance(history_context_turns, int)
        or history_context_turns < 0
    ):
        raise ValueError("Qwen35 history_context_turns must be a non-negative integer")
    history_context_old_turns = context.get("history_context_old_turns", 0)
    if (
        isinstance(history_context_old_turns, bool)
        or not isinstance(history_context_old_turns, int)
        or history_context_old_turns < 0
    ):
        raise ValueError("Qwen35 history_context_old_turns must be a non-negative integer")
    raw_old_mode = context.get("history_context_old_mode")
    history_context_old_mode = None if raw_old_mode is None else str(raw_old_mode).strip()
    if history_context_old_turns > 0 and not history_context_old_mode:
        raise ValueError("Qwen35 history_context_old_mode is required when the old layer is enabled")
    action_prompt = str(context.get("action_prompt_text", DEFAULT_ACTION_PROMPT_TEXT))
    return history_context_turns, history_context_old_turns, history_context_old_mode, action_prompt


class PlayerOnePolicy:
    """Wrap the maintained Player-1 agent and native-tool HTTP backend.

    Action duration and available tools come from the injected catalog game.
    """

    def __init__(
        self,
        backend_config: OpenAICompatibleConfig,
        *,
        action_format_retry_max: int = DEFAULT_QWEN35_ACTION_FORMAT_RETRY_MAX,
        backend_factory: QwenBackendFactory = _default_qwen_backend,
        agent_factory: Callable[[], GameAgent] = GameAgent,
        observe_remaining_turns: bool = False,
    ):
        if (
            isinstance(action_format_retry_max, bool)
            or not isinstance(action_format_retry_max, int)
            or action_format_retry_max < 0
        ):
            raise ValueError("Qwen35 action_format_retry_max must be a non-negative integer")
        self._base_backend_config = backend_config
        self._action_format_retry_max = action_format_retry_max
        self._observe_remaining_turns = observe_remaining_turns
        self._backend_factory = backend_factory
        self._activate_agent(agent_factory())
        self._backend: _MessageBackend | None = None
        self._instruction: str | None = None
        self._seed: int | None = None
        self._context: dict[str, Any] = {}
        self._history_context: HistoryContext | None = None
        self._pending_history_context_commit: _PendingHistoryContextCommit | None = None
        self._system_prompt = ""

    def _activate_agent(self, agent: GameAgent) -> None:
        agent_metadata = agent.metadata()
        required = {
            "action_format": "qwen3_coder_xml",
        }
        mismatches = {
            key: (required_value, agent_metadata.get(key))
            for key, required_value in required.items()
            if agent_metadata.get(key) != required_value
        }
        if mismatches:
            raise RuntimeError(f"Qwen35 Player-1 policy contract drifted: {mismatches}")

        action_duration_ms = agent_metadata.get("action_duration_ms")
        if isinstance(action_duration_ms, bool) or not isinstance(action_duration_ms, int) or action_duration_ms <= 0:
            raise RuntimeError("Qwen35 Player-1 agent must declare a positive integer action duration")
        self._agent = agent
        self._action_duration_ms = action_duration_ms
        self._agent_metadata = agent_metadata

    def reset(
        self,
        instruction: str,
        seed: int,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        instruction, seed, normalized_context = _validated_instruction_seed(
            instruction,
            seed,
            context,
        )
        history_context_turns, history_context_old_turns, history_context_old_mode, action_prompt = (
            _qwen_history_context(normalized_context)
        )
        backend_config = replace(self._base_backend_config, seed=seed)
        self._backend = self._backend_factory(backend_config, self._agent.model_tools)
        self._instruction = instruction
        self._seed = seed
        self._context = normalized_context
        self._pending_history_context_commit = None
        initial_messages = self._agent.build_initial_messages(instruction)
        self._system_prompt = initial_messages[0]["content"]
        self._history_context = HistoryContext(
            history_context_mode=self._agent_metadata["history_context_mode"],
            history_context_turns=history_context_turns,
            history_context_old_turns=history_context_old_turns,
            history_context_old_mode=history_context_old_mode,
            action_prompt_text=action_prompt,
            agent=self._agent,
            max_decisions=normalized_context["max_decisions"] if self._observe_remaining_turns else None,
        )
        self._history_context.reset(initial_messages)

    def act(self, image: Image.Image) -> PolicyStep:
        if self._backend is None or self._instruction is None or self._seed is None or self._history_context is None:
            raise RuntimeError("Reset Qwen35 policy before requesting an action")
        if self._pending_history_context_commit is not None:
            raise RuntimeError("Commit the previous Qwen35 action after environment execution before acting again")
        current_image = _rgb_copy(image)
        history_context_turns, history_context_old_turns, history_context_old_mode, _ = _qwen_history_context(
            self._context
        )
        history_context_request = self._history_context.build_request(current_image)
        messages = history_context_request.messages
        input_image_references = _input_image_references(
            messages,
            initial_prompt_message_count=history_context_request.episode_request.initial_prompt_message_count,
            history_context_info=history_context_request.history_context_info,
        )

        format_attempts: list[dict[str, Any]] = []
        attempt_backend = self._backend
        for format_attempt_index in range(self._action_format_retry_max + 1):
            format_attempt_seed = self._seed + format_attempt_index
            if format_attempt_index > 0:
                attempt_backend = self._backend_factory(
                    replace(self._base_backend_config, seed=format_attempt_seed),
                    self._agent.model_tools,
                )
            generation = attempt_backend.generate(messages)
            proposal = self._history_context.propose_generation(
                history_context_request,
                generation=generation,
            )
            draft = proposal.draft
            parsed_evidence = proposal_evidence(proposal)
            format_attempts.append(
                {
                    "attempt_index": format_attempt_index,
                    "seed": format_attempt_seed,
                    "generation": generation.to_dict(),
                    "parsed": {key: value for key, value in parsed_evidence.items() if key != "shared_episode"},
                    "transport": _transport_evidence(attempt_backend),
                    "shared_episode": parsed_evidence["shared_episode"],
                }
            )
            if draft.model_action_valid:
                break

        draft = proposal.draft
        control_action = thaw_episode_value(draft.requested_action)
        if (
            control_action.get("type") != "game_step_action"
            or control_action.get("duration_ms") != self._action_duration_ms
        ):
            raise RuntimeError(f"Qwen35 native agent returned a non-{self._action_duration_ms} ms control action")
        policy_step = PolicyStep(
            control_action=control_action,
            valid=draft.model_action_valid,
            invalid_reason=draft.invalid_reason,
            generation=generation,
            request_evidence={
                "message_count": len(messages),
                "history_context_turns": history_context_turns,
                "history_context_old_turns": history_context_old_turns,
                "history_context_old_mode": history_context_old_mode,
                "history_context": dict(history_context_request.history_context_info),
                "input_image_references": input_image_references,
                "action_format_retry_max": self._action_format_retry_max,
                "action_format_retry_attempts": len(format_attempts) - 1,
                "action_format_retry_exhausted": not draft.model_action_valid,
                "action_format_retry_seed_protocol": "reset_seed_plus_attempt_index_v1",
                "transport": _transport_evidence(attempt_backend),
            },
            parsed_evidence={
                **parsed_evidence,
                "format_attempts": format_attempts,
            },
        )
        self._pending_history_context_commit = _PendingHistoryContextCommit(
            policy_step=policy_step,
            proposal=proposal,
        )
        return policy_step

    def commit_after_successful_step(
        self,
        policy_step: PolicyStep,
        environment_step: EnvironmentStep,
    ) -> None:
        """Commit history context after a successful environment transition."""

        pending = self._pending_history_context_commit
        if pending is None:
            raise RuntimeError("No pending Qwen35 action is awaiting an execution receipt")
        if policy_step is not pending.policy_step:
            raise RuntimeError("Player-1 execution receipt does not match the pending Qwen35 action")
        if not isinstance(getattr(environment_step, "image", None), Image.Image):
            raise RuntimeError("Player-1 execution receipt is missing its post-step image")
        if not isinstance(getattr(environment_step, "info", None), Mapping):
            raise RuntimeError("Player-1 execution receipt is missing its post-step info")
        if not isinstance(getattr(environment_step, "terminated", None), bool) or not isinstance(
            getattr(environment_step, "truncated", None),
            bool,
        ):
            raise RuntimeError("Player-1 execution receipt has invalid terminal flags")
        if self._history_context is None:
            raise RuntimeError("Player-1 history context was reset before execution commit")
        self._history_context.commit_execution(
            pending.proposal,
            build_successful_action_outcome(
                pending.proposal,
                reward=environment_step.reward,
                terminated=environment_step.terminated,
                truncated=environment_step.truncated,
            ),
        )
        self._pending_history_context_commit = None

    def metadata(self) -> dict[str, Any]:
        return {
            "adapter": "qwen35_minestudio_official_policy_v1",
            "model_profile": self._agent_metadata["model_profile_id"],
            "model": self._base_backend_config.model,
            "protocol": (f"{self._agent_metadata['action_format']}/{self._agent_metadata['action_space_mode']}"),
            "action_format": self._agent_metadata["action_format"],
            "action_space_mode": self._agent_metadata["action_space_mode"],
            "action_duration_ms": self._action_duration_ms,
            "history_context_mode": self._agent_metadata["history_context_mode"],
            "chat_template": qwen_player1_chat_template_contract(self._base_backend_config.model),
            "sampling_seed_source": "reset.seed",
            "action_format_retry_max": self._action_format_retry_max,
            "action_format_retry_seed_protocol": "reset_seed_plus_attempt_index_v1",
        }


__all__ = [
    "DEFAULT_QWEN35_ACTION_FORMAT_RETRY_MAX",
    "QWEN35_ACTION_MAX_TOKENS",
    "PlayerOnePolicy",
]
