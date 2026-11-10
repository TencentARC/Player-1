"""Mode-based history-context policies shared by model agents and RL training."""

from __future__ import annotations

import re
from typing import Any

HISTORY_CONTEXT_MODE_V_T_A = "v_t_a"
HISTORY_CONTEXT_MODE_V_A = "v_a"
HISTORY_CONTEXT_MODE_A = "a"
HISTORY_CONTEXT_MODE_T_A = "t_a"
HISTORY_CONTEXT_MODE_T = "t"
OMITTED_IMAGE_PLACEHOLDER = "<image omitted>"
OMITTED_THINKING_PLACEHOLDER = "<thinking omitted>"
HISTORY_CONTEXT_MESSAGE_METADATA_KEY = "_player1_history_context"
_TEMPLATE_ACTIVE_ASSISTANT_FIELDS = frozenset(
    {
        "content",
        "reasoning_content",
        "tool_calls",
        HISTORY_CONTEXT_MESSAGE_METADATA_KEY,
    }
)
SUPPORTED_HISTORY_CONTEXT_MODES = frozenset(
    {
        HISTORY_CONTEXT_MODE_T,
        HISTORY_CONTEXT_MODE_A,
        HISTORY_CONTEXT_MODE_T_A,
        HISTORY_CONTEXT_MODE_V_A,
        HISTORY_CONTEXT_MODE_V_T_A,
    }
)
COLLAPSED_HISTORY_CONTEXT_MODES = frozenset(
    {
        HISTORY_CONTEXT_MODE_T,
        HISTORY_CONTEXT_MODE_A,
        HISTORY_CONTEXT_MODE_T_A,
    }
)

HISTORY_CONTEXT_REPLAY_SOURCES = frozenset({"admitted", "fallback"})

HistoryContextInfo = dict[str, Any]

_THINK_OPEN_PATTERN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE_PATTERN = re.compile(r"</think>", re.IGNORECASE)
_ACTION_TAG_PATTERN = re.compile(r"</?(?:tool_call|action)\b", re.IGNORECASE)


def _is_observation_message(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(item, dict) and item.get("type") == "image" for item in content)


def build_history_context_metadata(
    history_context_mode: str,
    canonical_action: str,
    *,
    replay_source: str,
    canonical_think_action: str | None = None,
) -> dict[str, Any]:
    """Build trusted metadata for one future-context replay."""

    mode = require_history_context_mode(history_context_mode)
    normalized_action = str(canonical_action or "").strip()
    if not normalized_action:
        raise ValueError(f"{mode} requires a non-empty canonical action")
    normalized_source = str(replay_source or "").strip()
    if normalized_source not in HISTORY_CONTEXT_REPLAY_SOURCES:
        expected = ", ".join(sorted(HISTORY_CONTEXT_REPLAY_SOURCES))
        raise ValueError(f"Unsupported {mode} replay source {replay_source!r}; expected {expected}")
    metadata: dict[str, Any] = {
        "mode": mode,
        "canonical_action": normalized_action,
        "replay_source": normalized_source,
    }
    normalized_think_action = str(canonical_think_action or "").strip()
    if normalized_source == "fallback" and normalized_think_action:
        raise ValueError(f"{mode} cannot attach thinking to an executed fallback")
    if normalized_think_action and not normalized_think_action.endswith(normalized_action):
        raise ValueError(f"{mode} thinking/action output does not end in its canonical action")
    if normalized_think_action:
        metadata["canonical_think_action"] = normalized_think_action
    compatible_modes = {
        HISTORY_CONTEXT_MODE_A,
        HISTORY_CONTEXT_MODE_V_A,
        HISTORY_CONTEXT_MODE_V_T_A,
    }
    if normalized_source == "admitted" and normalized_think_action:
        compatible_modes.add(HISTORY_CONTEXT_MODE_T_A)
        compatible_modes.add(HISTORY_CONTEXT_MODE_T)
    metadata["compatible_modes"] = sorted(compatible_modes)
    return metadata


def _trusted_history_context_metadata(
    message: dict[str, Any],
    *,
    expected_mode: str,
    required: bool,
) -> dict[str, Any] | None:
    metadata = message.get(HISTORY_CONTEXT_MESSAGE_METADATA_KEY)
    if not isinstance(metadata, dict):
        if required:
            raise ValueError(f"{expected_mode} refuses to replay an assistant message without trusted metadata")
        return None
    compatible_modes = metadata.get("compatible_modes")
    mode_is_compatible = (
        isinstance(compatible_modes, (list, tuple))
        and all(isinstance(mode, str) for mode in compatible_modes)
        and expected_mode in compatible_modes
    )
    if not mode_is_compatible:
        if required:
            raise ValueError(f"{expected_mode} refuses assistant metadata without a compatible replay projection")
        return None
    replay_source = metadata.get("replay_source")
    if replay_source not in HISTORY_CONTEXT_REPLAY_SOURCES:
        if required:
            raise ValueError(f"{expected_mode} assistant metadata has an invalid replay source")
        return None
    canonical_action = metadata.get("canonical_action")
    if not isinstance(canonical_action, str) or not canonical_action.strip():
        if required:
            raise ValueError(f"{expected_mode} assistant metadata is missing its canonical action")
        return None
    return metadata


def _canonical_action(message: dict[str, Any], *, expected_mode: str, required: bool = True) -> str | None:
    metadata = _trusted_history_context_metadata(
        message,
        expected_mode=expected_mode,
        required=required,
    )
    if metadata is None:
        return None
    return str(metadata["canonical_action"]).strip()


def _canonical_think_action(
    message: dict[str, Any],
    *,
    expected_mode: str,
    action_fallback: bool,
) -> str | None:
    metadata = _trusted_history_context_metadata(
        message,
        expected_mode=expected_mode,
        required=action_fallback,
    )
    if metadata is None:
        return None
    canonical_output = metadata.get("canonical_think_action")
    if isinstance(canonical_output, str) and canonical_output.strip():
        normalized_output = canonical_output.strip()
        canonical_action = str(metadata["canonical_action"]).strip()
        if metadata["replay_source"] == "fallback" or not normalized_output.endswith(canonical_action):
            if action_fallback:
                raise ValueError(f"{expected_mode} assistant metadata has an inconsistent thinking/action replay")
            return None
        return normalized_output
    if action_fallback:
        return str(metadata["canonical_action"]).strip()
    return None


def canonicalize_think_action_output(
    output: str,
    *,
    action_span: tuple[int, int],
    canonical_action: str,
) -> str | None:
    """Combine validated reasoning with exactly one canonical action block."""

    action_start, action_end = action_span
    if action_start < 0 or action_end <= action_start or action_end > len(output) or output[action_end:].strip():
        return None
    canonical_action = canonical_action.strip()
    if not canonical_action:
        return None

    reasoning = output[:action_start].strip()
    leading_open = _THINK_OPEN_PATTERN.match(reasoning)
    if leading_open is not None:
        reasoning = reasoning[leading_open.end() :].lstrip()
    trailing_closes = list(_THINK_CLOSE_PATTERN.finditer(reasoning))
    if trailing_closes and not reasoning[trailing_closes[-1].end() :].strip():
        reasoning = reasoning[: trailing_closes[-1].start()].rstrip()

    if (
        _THINK_OPEN_PATTERN.search(reasoning)
        or _THINK_CLOSE_PATTERN.search(reasoning)
        or _ACTION_TAG_PATTERN.search(reasoning)
    ):
        return None
    if not reasoning:
        return None

    return render_canonical_think_action(reasoning, canonical_action)


def render_canonical_think_action(reasoning: str, canonical_action: str) -> str:
    """Render the assistant text shared by RL history replay and cold-start SFT."""

    normalized_reasoning = str(reasoning or "").strip()
    normalized_action = str(canonical_action or "").strip()
    if not normalized_reasoning:
        raise ValueError("canonical thinking/action output requires non-empty reasoning")
    if not normalized_action:
        raise ValueError("canonical thinking/action output requires a non-empty action")
    if (
        _THINK_OPEN_PATTERN.search(normalized_reasoning)
        or _THINK_CLOSE_PATTERN.search(normalized_reasoning)
        or _ACTION_TAG_PATTERN.search(normalized_reasoning)
    ):
        raise ValueError("canonical reasoning cannot contain thinking or action markup")
    return f"<think>\n{normalized_reasoning}\n</think>\n\n{normalized_action}"


def _observation_with_collapsed_image(
    observation: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    """Replace one historical screenshot while preserving its user turn."""

    content = observation.get("content")
    if not isinstance(content, list):
        raise TypeError(f"{mode} requires observation content to be a multimodal list")
    image_offsets = [
        index for index, item in enumerate(content) if isinstance(item, dict) and item.get("type") == "image"
    ]
    if len(image_offsets) != 1:
        raise ValueError(f"{mode} requires exactly one screenshot per retained observation")
    selected_content = list(content)
    selected_content[image_offsets[0]] = {
        "type": "text",
        "text": f"{OMITTED_IMAGE_PLACEHOLDER}\n",
    }
    return {**observation, "content": selected_content}


def _standard_history_turns(
    messages: list[dict[str, Any]],
    initial_prompt_message_count: int,
    *,
    mode: str,
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, dict[str, Any], dict[str, Any]]],
    dict[str, Any],
]:
    """Split a committed ledger into indexed history pairs and the current observation."""

    if initial_prompt_message_count < 0:
        raise ValueError("initial_prompt_message_count must be non-negative")
    prompt_messages = list(messages[:initial_prompt_message_count])
    history_messages = list(messages[initial_prompt_message_count:])
    observation_offsets = [index for index, message in enumerate(history_messages) if _is_observation_message(message)]
    if not observation_offsets:
        raise ValueError(f"{mode} requires a current user observation containing an image")
    current_observation_offset = observation_offsets[-1]
    if current_observation_offset != len(history_messages) - 1:
        raise ValueError(f"{mode} requires the current observation to be the final history message")

    historical_turns: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for turn_index, observation_offset in enumerate(observation_offsets[:-1]):
        next_observation_offset = observation_offsets[turn_index + 1]
        turn_messages = history_messages[observation_offset:next_observation_offset]
        if len(turn_messages) != 2 or turn_messages[1].get("role") != "assistant":
            raise ValueError(f"{mode} requires standard user/assistant historical turns")
        historical_turns.append((turn_index, turn_messages[0], turn_messages[1]))
    return prompt_messages, historical_turns, history_messages[current_observation_offset]


def _project_history_turns(
    turns: list[tuple[int, dict[str, Any], dict[str, Any]]],
    *,
    mode: str,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Project indexed turns through one visual or collapsed replay mode."""

    projected: list[dict[str, Any]] = []
    retained_indices: list[int] = []
    for turn_index, observation, assistant in turns:
        if mode in {HISTORY_CONTEXT_MODE_T, HISTORY_CONTEXT_MODE_T_A, HISTORY_CONTEXT_MODE_V_T_A}:
            canonical_output = _canonical_think_action(
                assistant,
                expected_mode=mode,
                action_fallback=mode == HISTORY_CONTEXT_MODE_V_T_A,
            )
            if canonical_output is None:
                # t_a is strict: the candidate consumes its configured slot,
                # but the incomplete pair is omitted and no old turn fills it.
                continue
            if mode == HISTORY_CONTEXT_MODE_T:
                action = str(assistant[HISTORY_CONTEXT_MESSAGE_METADATA_KEY]["canonical_action"]).strip()
                canonical_output = canonical_output[:-len(action)].rstrip()
        else:
            canonical_output = _canonical_action(assistant, expected_mode=mode)
            assert canonical_output is not None
            canonical_output = f"{OMITTED_THINKING_PLACEHOLDER}\n{canonical_output}"

        projected.append(
            _observation_with_collapsed_image(observation, mode=mode)
            if mode in COLLAPSED_HISTORY_CONTEXT_MODES
            else observation
        )
        projected.append(
            {key: value for key, value in assistant.items() if key not in _TEMPLATE_ACTIVE_ASSISTANT_FIELDS}
            | {"content": canonical_output}
        )
        retained_indices.append(turn_index)
    return projected, retained_indices


def _select_history_context_layers(
    messages: list[dict[str, Any]],
    initial_prompt_message_count: int,
    history_context_turns: int | None,
    *,
    history_context_mode: str,
    history_context_old_turns: int | None,
    history_context_old_mode: str | None,
) -> tuple[list[dict[str, Any]], HistoryContextInfo]:
    """Project one standard ledger through primary and optional old layers."""

    prompt_messages, historical_turns, current_observation = _standard_history_turns(
        messages,
        initial_prompt_message_count,
        mode=history_context_mode,
    )
    total_history_turns = len(historical_turns)
    primary_capacity = total_history_turns if history_context_turns is None else max(0, int(history_context_turns))
    primary_start = max(0, total_history_turns - primary_capacity)
    primary_candidates = historical_turns[primary_start:]

    old_end = primary_start
    if history_context_old_mode is None:
        old_capacity = 0
    else:
        old_capacity = old_end if history_context_old_turns is None else max(0, int(history_context_old_turns))
    old_start = max(0, old_end - old_capacity)
    old_candidates = historical_turns[old_start:old_end]

    if history_context_old_mode is None:
        old_messages: list[dict[str, Any]] = []
        retained_old_indices: list[int] = []
    else:
        old_messages, retained_old_indices = _project_history_turns(
            old_candidates,
            mode=history_context_old_mode,
        )
    primary_messages, retained_primary_indices = _project_history_turns(
        primary_candidates,
        mode=history_context_mode,
    )
    retained_indices = retained_old_indices + retained_primary_indices
    retained_history_context_turns = len(retained_indices)
    requested_old_turns = old_capacity
    requested_primary_turns = primary_capacity
    selected_messages = prompt_messages + old_messages + primary_messages + [current_observation]
    info: HistoryContextInfo = {
        "requested_history_context_turns": requested_primary_turns,
        "retained_history_context_turns": retained_history_context_turns,
        "dropped_history_context_turns": total_history_turns - retained_history_context_turns,
        "total_history_context_turns": total_history_turns,
        "retained_history_context_indices": retained_indices,
    }
    if history_context_old_mode is None:
        if history_context_mode in COLLAPSED_HISTORY_CONTEXT_MODES:
            info.update(
                {
                    "retained_assistant_outputs": retained_history_context_turns,
                    "dropped_assistant_outputs": total_history_turns - retained_history_context_turns,
                }
            )
        return selected_messages, info

    info.update(
        {
            "history_context_old_mode": history_context_old_mode,
            "requested_history_context_turns": requested_old_turns + requested_primary_turns,
            "requested_primary_history_context_turns": requested_primary_turns,
            "retained_primary_history_context_turns": len(retained_primary_indices),
            "dropped_primary_history_context_turns": len(primary_candidates) - len(retained_primary_indices),
            "requested_old_history_context_turns": requested_old_turns,
            "retained_old_history_context_turns": len(retained_old_indices),
            "dropped_old_history_context_turns": len(old_candidates) - len(retained_old_indices),
        }
    )
    return selected_messages, info


def require_history_context_mode(history_context_mode: str) -> str:
    """Return one explicit supported history-context mode."""

    normalized = str(history_context_mode or "").strip()
    if normalized not in SUPPORTED_HISTORY_CONTEXT_MODES:
        expected = ", ".join(sorted(SUPPORTED_HISTORY_CONTEXT_MODES))
        raise ValueError(f"Unsupported history_context_mode {history_context_mode!r}; expected {expected}")
    return normalized


def select_history_context_messages(
    *,
    messages: list[dict[str, Any]],
    initial_prompt_message_count: int,
    history_context_turns: int | None,
    history_context_mode: str,
    history_context_old_turns: int | None = 0,
    history_context_old_mode: str | None = None,
) -> tuple[list[dict[str, Any]], HistoryContextInfo]:
    """Apply the primary mode plus an optional old collapsed layer."""

    mode = require_history_context_mode(history_context_mode)
    if history_context_old_turns is not None:
        if isinstance(history_context_old_turns, bool) or not isinstance(history_context_old_turns, int):
            raise TypeError("history_context_old_turns must be an integer or None")
        if history_context_old_turns < 0:
            raise ValueError("history_context_old_turns must be non-negative or None")
    old_layer_enabled = history_context_old_turns is None or history_context_old_turns > 0
    old_mode = None
    if old_layer_enabled:
        if history_context_turns is None:
            raise ValueError("history_context_turns cannot be None when an old history layer is enabled")
        old_mode = require_history_context_mode(history_context_old_mode or "")
        if old_mode not in COLLAPSED_HISTORY_CONTEXT_MODES:
            expected = ", ".join(sorted(COLLAPSED_HISTORY_CONTEXT_MODES))
            raise ValueError(f"history_context_old_mode must be one of {expected}, got {old_mode!r}")
    selected_messages, info = _select_history_context_layers(
        messages,
        initial_prompt_message_count,
        history_context_turns,
        history_context_mode=mode,
        history_context_old_turns=history_context_old_turns if old_layer_enabled else 0,
        history_context_old_mode=old_mode,
    )
    return selected_messages, {"history_context_mode": mode, **info}


__all__ = [
    "COLLAPSED_HISTORY_CONTEXT_MODES",
    "OMITTED_IMAGE_PLACEHOLDER",
    "OMITTED_THINKING_PLACEHOLDER",
    "HISTORY_CONTEXT_MESSAGE_METADATA_KEY",
    "HISTORY_CONTEXT_MODE_A",
    "HISTORY_CONTEXT_MODE_T",
    "HISTORY_CONTEXT_MODE_T_A",
    "HISTORY_CONTEXT_MODE_V_A",
    "HISTORY_CONTEXT_MODE_V_T_A",
    "HISTORY_CONTEXT_REPLAY_SOURCES",
    "SUPPORTED_HISTORY_CONTEXT_MODES",
    "build_history_context_metadata",
    "canonicalize_think_action_output",
    "render_canonical_think_action",
    "require_history_context_mode",
    "select_history_context_messages",
]
