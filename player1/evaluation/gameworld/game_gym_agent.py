"""GameGym-trained model agent for the vendored GameWorld runtime.

This adapter is intentionally self-contained.  It consumes the serialized
role contract produced by GameGym, but imports neither the outer ``game_gym``
package nor GameWorld internals.  The class owns the model-facing conversation,
strict Control V0.5 XML parsing, role-level admission, fallback selection, and
compilation into the ``game_step_action`` frame consumed by
``game_gym_control.py``.
"""

from __future__ import annotations

import itertools
import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


COLLAPSED_IMAGE_PLACEHOLDER = "<image collapsed>"
SUPPORTED_HISTORY_CONTEXT_MODES = frozenset(("v_t_a", "v_a", "a", "t_a"))
COLLAPSED_HISTORY_CONTEXT_MODES = frozenset(("a", "t_a"))

_TOOL_BLOCK_PATTERN = re.compile(r"<tool_call\b[\s\S]*?</tool_call>", re.IGNORECASE)
_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*<function=(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)>"
    r"(?P<body>[\s\S]*?)</function>\s*</tool_call>",
    re.IGNORECASE,
)
_PARAMETER_PATTERN = re.compile(
    r"<parameter=(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)>"
    r"(?P<value>[\s\S]*?)</parameter>",
    re.IGNORECASE,
)
_THINK_OPEN_PATTERN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE_PATTERN = re.compile(r"</think>", re.IGNORECASE)
_ACTION_TAG_PATTERN = re.compile(r"</?(?:tool_call|action)\b", re.IGNORECASE)
_PARAMETER_CLOSE_PATTERN = re.compile(r"</parameter>", re.IGNORECASE)


def _clone(value: Any) -> Any:
    """Copy chat/JSON containers while retaining opaque image references."""

    if isinstance(value, Mapping):
        return {str(key): _clone(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_clone(item) for item in value]
    return value


def _message_image_objects(message: Mapping[str, Any]) -> tuple[Any, ...]:
    content = message.get("content")
    if not isinstance(content, (tuple, list)):
        return ()
    return tuple(
        item["image"]
        for item in content
        if isinstance(item, Mapping) and item.get("type") == "image" and item.get("image") is not None
    )


def _close_image_objects(images: Sequence[Any], *, protected_ids: frozenset[int] = frozenset()) -> tuple[Any, ...]:
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
    """Release committed image buffers outside the live visual window."""

    def __init__(self, retained_turns: int) -> None:
        self.retained_turns = retained_turns
        self._committed: deque[tuple[Any, ...]] = deque()

    def track_and_prune(
        self,
        observation: Mapping[str, Any],
        *,
        protected_observations: Sequence[Mapping[str, Any]],
    ) -> None:
        self._committed.append(_message_image_objects(observation))
        protected_ids = frozenset(
            id(image)
            for message in protected_observations
            for image in _message_image_objects(message)
        )
        evict_count = max(0, len(self._committed) - self.retained_turns)
        retained_evictions: list[tuple[Any, ...]] = []
        for _ in range(evict_count):
            remaining = _close_image_objects(self._committed.popleft(), protected_ids=protected_ids)
            if remaining:
                retained_evictions.append(remaining)
        self._committed.extendleft(reversed(retained_evictions))

    def release_pending(self, observation: Mapping[str, Any]) -> None:
        _close_image_objects(_message_image_objects(observation))

    def reset(self) -> None:
        images = tuple(image for turn_images in self._committed for image in turn_images)
        self._committed.clear()
        _close_image_objects(images)


def _require_nonnegative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_mode(value: Any, *, name: str) -> str:
    mode = str(value or "").strip()
    if mode not in SUPPORTED_HISTORY_CONTEXT_MODES:
        expected = ", ".join(sorted(SUPPORTED_HISTORY_CONTEXT_MODES))
        raise ValueError(f"{name} must be one of {expected}, got {value!r}")
    return mode


class _DuplicateJSONObjectMemberError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONObjectMemberError(key)
        result[key] = value
    return result


def _decode_parameter(value: str) -> Any:
    stripped = value.strip()
    try:
        return json.loads(stripped, object_pairs_hook=_strict_object)
    except json.JSONDecodeError:
        return stripped


def _parse_tool_block(block: str) -> dict[str, Any] | None:
    match = _TOOL_CALL_PATTERN.fullmatch(block)
    if match is None:
        return None
    arguments: dict[str, Any] = {}
    cursor = 0
    try:
        for parameter in _PARAMETER_PATTERN.finditer(match.group("body")):
            if match.group("body")[cursor : parameter.start()].strip():
                return None
            name = parameter.group("name")
            if name in arguments:
                return None
            arguments[name] = _decode_parameter(parameter.group("value"))
            cursor = parameter.end()
    except _DuplicateJSONObjectMemberError:
        return None
    if match.group("body")[cursor:].strip():
        return None
    return {"tool_name": match.group("name"), "arguments": arguments}


def _parse_control_frame(text: str) -> tuple[dict[str, Any], tuple[int, int]] | None:
    spans = [match.span() for match in _TOOL_BLOCK_PATTERN.finditer(text)]
    if not spans or len(spans) > 2 or text[spans[-1][1] :].strip():
        return None
    if any(text[left[1] : right[0]].strip() for left, right in itertools.pairwise(spans)):
        return None
    calls = [_parse_tool_block(text[start:end]) for start, end in spans]
    if any(call is None for call in calls):
        return None
    normalized = [call for call in calls if call is not None]
    names = [str(call["tool_name"]) for call in normalized]
    if names == ["wait"]:
        if normalized[0]["arguments"]:
            return None
    else:
        if "wait" in names or len(set(names)) != len(names):
            return None
        if not set(names) <= {"key_control", "mouse_control"}:
            return None
        allowed = {
            "key_control": frozenset(("key_hold", "key_tap")),
            "mouse_control": frozenset(("mouse_move", "mouse_click", "mouse_hold", "mouse_scroll")),
        }
        if any(
            not call["arguments"] or not call["arguments"].keys() <= allowed[call["tool_name"]] for call in normalized
        ):
            return None
        by_name = {call["tool_name"]: call for call in normalized}
        normalized = [by_name[name] for name in ("mouse_control", "key_control") if name in by_name]
    return (
        {"action_space_mode": "control_v0_5", "tool_calls": normalized},
        (spans[0][0], spans[-1][1]),
    )


def _render_parameter(value: Any) -> str:
    if isinstance(value, str):
        if _PARAMETER_CLOSE_PATTERN.search(value):
            raise ValueError("String action arguments cannot contain </parameter>")
        try:
            json.loads(value.strip())
        except json.JSONDecodeError:
            return value
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonicalize_think_action(
    output: str,
    *,
    action_span: tuple[int, int],
    canonical_action: str,
) -> str | None:
    start, end = action_span
    if start < 0 or end <= start or end > len(output) or output[end:].strip():
        return None
    reasoning = output[:start].strip()
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
    return f"<think>\n{reasoning}\n</think>\n\n{canonical_action}"


@dataclass(frozen=True, slots=True)
class GameGymAgentRequest:
    """Exact model messages and history accounting for one pending turn."""

    messages: tuple[dict[str, Any], ...]
    context_info: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GameGymAgentProposal:
    """Parsed model action and concrete GameWorld runtime request."""

    decoded_output: str
    parsed_payload: dict[str, Any] | None
    requested_action: dict[str, Any]
    model_action_valid: bool
    invalid_reason: str | None
    fallback_used: bool
    action_span: tuple[int, int] | None
    canonical_action: str
    canonical_think_action: str | None


@dataclass(slots=True)
class _HistoryTurn:
    observation: dict[str, Any]
    canonical_action: str
    canonical_think_action: str | None


class GameGymAgent:
    """Stateful trained-model agent implementing the GameGym prompt contract."""

    def __init__(
        self,
        role_contract: Mapping[str, Any],
        *,
        history_context_turns: int = 0,
        history_context_old_turns: int = 0,
        history_context_old_mode: str | None = None,
    ) -> None:
        self.contract = _clone(role_contract)
        if self.contract.get("action_format") != "qwen3_coder_xml":
            raise ValueError("GameWorld GameGymAgent requires qwen3_coder_xml")
        if self.contract.get("action_space_mode") != "control_v0_5":
            raise ValueError("GameWorld GameGymAgent requires control_v0_5")
        self.history_context_mode = _require_mode(
            self.contract.get("history_context_mode"), name="history_context_mode"
        )
        self.history_context_turns = _require_nonnegative_int(history_context_turns, name="history_context_turns")
        self.history_context_old_turns = _require_nonnegative_int(
            history_context_old_turns, name="history_context_old_turns"
        )
        self.history_context_old_mode = None
        if self.history_context_old_turns:
            self.history_context_old_mode = _require_mode(history_context_old_mode, name="history_context_old_mode")
            if self.history_context_old_mode not in COLLAPSED_HISTORY_CONTEXT_MODES:
                raise ValueError("history_context_old_mode must be a or t_a")

        initial_messages = self.contract.get("initial_messages")
        if not isinstance(initial_messages, list) or not initial_messages:
            raise ValueError("GameWorld role contract requires initial_messages")
        self.initial_messages = _clone(initial_messages)
        self.model_tools = _clone(self.contract.get("model_tools") or [])
        action_prompt_text = self.contract.get("action_prompt_text")
        if not isinstance(action_prompt_text, str) or not action_prompt_text.strip():
            raise ValueError("GameWorld role contract requires action_prompt_text")
        self.action_prompt_text = action_prompt_text
        self.allowed_keys = frozenset(str(key) for key in self.contract.get("allowed_keys") or [])
        self.mouse_buttons = frozenset(str(key) for key in self.contract.get("mouse_buttons") or [])
        self.action_map = _clone(self.contract.get("unified_action_space_map") or {})
        self.fallback_action = _clone(self.contract.get("fallback_action") or {})
        if not self.model_tools or not self.action_map:
            raise ValueError("GameWorld role contract requires model tools and runtime action mappings")
        if not self.fallback_action.get("type") or not self.fallback_action.get("id"):
            raise ValueError("GameWorld role contract requires a concrete fallback_action")
        self._argument_order: dict[str, tuple[str, ...]] = {}
        for spec in self.contract.get("runtime_tool_specs") or []:
            schema = spec.get("argument_schema") if isinstance(spec, Mapping) else None
            properties = schema.get("properties") if isinstance(schema, Mapping) else None
            self._argument_order[str(spec.get("id") or "")] = (
                tuple(str(name) for name in properties) if isinstance(properties, Mapping) else ()
            )
        key_schema = self.action_map.get("key_control", {}).get("argument_schema", {})
        key_properties = key_schema.get("properties", {}) if isinstance(key_schema, Mapping) else {}
        key_hold_schema = key_properties.get("key_hold", {}) if isinstance(key_properties, Mapping) else {}
        key_items_schema = key_hold_schema.get("items", {}) if isinstance(key_hold_schema, Mapping) else {}
        key_enum = key_items_schema.get("enum", ()) if isinstance(key_items_schema, Mapping) else ()
        self._runtime_keys = frozenset(str(key) for key in key_enum)
        mouse_schema = self.action_map.get("mouse_control", {}).get("argument_schema", {})
        mouse_properties = mouse_schema.get("properties", {}) if isinstance(mouse_schema, Mapping) else {}
        click_schema = mouse_properties.get("mouse_click", {}) if isinstance(mouse_properties, Mapping) else {}
        mouse_enum = click_schema.get("enum", ()) if isinstance(click_schema, Mapping) else ()
        self._runtime_mouse_buttons = frozenset(str(button) for button in mouse_enum)
        self._history: list[_HistoryTurn] = []
        retained_image_turns = (
            0 if self.history_context_mode in COLLAPSED_HISTORY_CONTEXT_MODES else self.history_context_turns
        )
        self._image_retention = _ObservationImageRetention(retained_image_turns)
        self._pending_observation: dict[str, Any] | None = None
        self._pending_request: GameGymAgentRequest | None = None
        self._pending_proposal: GameGymAgentProposal | None = None

    def reset(self) -> None:
        if self._pending_observation is not None:
            self._image_retention.release_pending(self._pending_observation)
        self._image_retention.reset()
        self._history.clear()
        self._clear_pending()

    @property
    def committed_turns(self) -> int:
        return len(self._history)

    def _observation_message(self, image: Any) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": self.action_prompt_text},
            ],
        }

    @staticmethod
    def _collapsed_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
        selected = _clone(observation)
        content = selected.get("content")
        if not isinstance(content, list):
            raise ValueError("Historical GameWorld observation must have multimodal content")
        offsets = [
            index for index, item in enumerate(content) if isinstance(item, Mapping) and item.get("type") == "image"
        ]
        if len(offsets) != 1:
            raise ValueError("Historical GameWorld observation must contain exactly one image")
        content[offsets[0]] = {"type": "text", "text": f"{COLLAPSED_IMAGE_PLACEHOLDER}\n"}
        return selected

    def _project(self, indexed_turns: Sequence[tuple[int, _HistoryTurn]], *, mode: str) -> tuple[list[dict], list[int]]:
        messages: list[dict[str, Any]] = []
        retained: list[int] = []
        for index, turn in indexed_turns:
            if mode in {"t_a", "v_t_a"}:
                assistant = turn.canonical_think_action
                if assistant is None and mode == "t_a":
                    continue
                if assistant is None:
                    assistant = turn.canonical_action
            else:
                assistant = turn.canonical_action
            observation = (
                self._collapsed_observation(turn.observation)
                if mode in COLLAPSED_HISTORY_CONTEXT_MODES
                else _clone(turn.observation)
            )
            messages.extend((observation, {"role": "assistant", "content": assistant}))
            retained.append(index)
        return messages, retained

    def _select_context(self, current: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        indexed = list(enumerate(self._history))
        total = len(indexed)
        primary_start = max(0, total - self.history_context_turns)
        primary_candidates = indexed[primary_start:]
        old_end = primary_start
        old_start = max(0, old_end - self.history_context_old_turns)
        old_candidates = indexed[old_start:old_end]

        old_messages: list[dict[str, Any]] = []
        retained_old: list[int] = []
        if self.history_context_old_mode is not None:
            old_messages, retained_old = self._project(old_candidates, mode=self.history_context_old_mode)
        primary_messages, retained_primary = self._project(primary_candidates, mode=self.history_context_mode)
        retained = retained_old + retained_primary
        messages = _clone(self.initial_messages) + old_messages + primary_messages + [_clone(current)]
        info: dict[str, Any] = {
            "history_context_mode": self.history_context_mode,
            "requested_history_context_turns": self.history_context_turns,
            "retained_history_context_turns": len(retained),
            "dropped_history_context_turns": total - len(retained),
            "total_history_context_turns": total,
            "retained_history_context_indices": retained,
        }
        if self.history_context_old_mode is None:
            if self.history_context_mode in COLLAPSED_HISTORY_CONTEXT_MODES:
                info.update(
                    {
                        "retained_assistant_outputs": len(retained),
                        "dropped_assistant_outputs": total - len(retained),
                    }
                )
            return messages, info
        info.update(
            {
                "history_context_old_mode": self.history_context_old_mode,
                "requested_history_context_turns": (self.history_context_old_turns + self.history_context_turns),
                "requested_primary_history_context_turns": self.history_context_turns,
                "retained_primary_history_context_turns": len(retained_primary),
                "dropped_primary_history_context_turns": len(primary_candidates) - len(retained_primary),
                "requested_old_history_context_turns": self.history_context_old_turns,
                "retained_old_history_context_turns": len(retained_old),
                "dropped_old_history_context_turns": len(old_candidates) - len(retained_old),
            }
        )
        return messages, info

    def build_request(self, image: Any) -> GameGymAgentRequest:
        if self._pending_observation is not None:
            raise RuntimeError("Cannot open a GameWorld model turn while another turn is pending")
        observation = self._observation_message(image)
        messages, context_info = self._select_context(observation)
        request = GameGymAgentRequest(tuple(messages), context_info)
        self._pending_observation = observation
        self._pending_request = request
        self._pending_proposal = None
        return request

    def cancel_turn(self) -> None:
        if self._pending_observation is not None:
            self._image_retention.release_pending(self._pending_observation)
        self._clear_pending()

    def _clear_pending(self) -> None:
        self._pending_observation = None
        self._pending_request = None
        self._pending_proposal = None

    def _render_call(self, call: Mapping[str, Any]) -> str:
        name = str(call.get("tool_name") or "")
        arguments = call.get("arguments")
        if not name or not isinstance(arguments, Mapping):
            raise ValueError("Canonical tool call requires name and arguments")
        order = self._argument_order.get(name, ())
        names = [key for key in order if key in arguments]
        names.extend(str(key) for key in arguments if key not in names)
        lines = ["<tool_call>", f"<function={name}>"]
        for key in names:
            lines.extend((f"<parameter={key}>", _render_parameter(arguments[key]), "</parameter>"))
        lines.extend(("</function>", "</tool_call>"))
        return "\n".join(lines)

    def render_action_frame(self, frame: Mapping[str, Any]) -> str:
        calls = frame.get("tool_calls")
        if frame.get("action_space_mode") != "control_v0_5" or not isinstance(calls, list):
            raise ValueError("Canonical action rendering requires a Control V0.5 frame")
        return "\n".join(self._render_call(call) for call in calls)

    @staticmethod
    def _integer(value: Any, *, minimum: int, maximum: int) -> bool:
        return not isinstance(value, bool) and isinstance(value, int) and minimum <= value <= maximum

    def _validate_and_compile(self, frame: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        calls = frame.get("tool_calls")
        if not isinstance(calls, list):
            return None, "invalid_control_frame"
        by_name = {str(call["tool_name"]): call["arguments"] for call in calls}
        if list(by_name) == ["wait"]:
            mapped = self.action_map.get("wait")
            return (_clone(self.fallback_action if mapped else None), None if mapped else "unknown_tool_name")

        durations: set[int] = set()
        for name, arguments in by_name.items():
            mapped = self.action_map.get(name)
            if not isinstance(mapped, Mapping):
                return None, "unknown_tool_name"
            durations.add(int(mapped.get("duration_ms", 200)))
            if not isinstance(arguments, Mapping):
                return None, "invalid_arguments"
        if len(durations) != 1:
            raise ValueError("GameWorld Control V0.5 mappings must use one duration")

        key = by_name.get("key_control", {})
        held = key.get("key_hold")
        tapped = key.get("key_tap")
        for values in (held, tapped):
            if values is None:
                continue
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(item, str) or item not in self._runtime_keys for item in values)
                or len(values) != len(set(values))
            ):
                return None, "invalid_arguments"
        unsupported_keys = sorted((set(held or ()) | set(tapped or ())) - self.allowed_keys)
        if unsupported_keys:
            return None, f"gameworld_key_not_allowed:{','.join(unsupported_keys)}"
        if set(held or ()) & set(tapped or ()):
            return None, "invalid_arguments"

        mouse = by_name.get("mouse_control", {})
        move = mouse.get("mouse_move")
        if move is not None:
            if not isinstance(move, Mapping):
                return None, "invalid_arguments"
            mode = move.get("mode")
            if mode == "relative":
                valid_move = set(move) == {"mode", "dx", "dy"} and all(
                    self._integer(move.get(axis), minimum=-1000, maximum=1000) for axis in ("dx", "dy")
                )
            elif mode == "absolute":
                valid_move = set(move) == {"mode", "x", "y"} and all(
                    self._integer(move.get(axis), minimum=0, maximum=1000) for axis in ("x", "y")
                )
            else:
                valid_move = False
            if not valid_move:
                return None, "invalid_arguments"
        click = mouse.get("mouse_click")
        hold = mouse.get("mouse_hold")
        if click is not None and (not isinstance(click, str) or click not in self._runtime_mouse_buttons):
            return None, "invalid_arguments"
        if hold is not None and (not isinstance(hold, str) or hold not in self._runtime_mouse_buttons):
            return None, "invalid_arguments"
        if click is not None and click not in self.mouse_buttons:
            return None, f"gameworld_mouse_button_not_allowed:{click}"
        if hold is not None and hold not in self.mouse_buttons:
            return None, f"gameworld_mouse_button_not_allowed:{hold}"
        if click is not None and click == hold:
            return None, "invalid_arguments"
        scroll = mouse.get("mouse_scroll")
        if scroll is not None and (not isinstance(scroll, str) or scroll not in {"up", "down"}):
            return None, "invalid_arguments"
        if scroll is not None and not self.mouse_buttons:
            return None, "gameworld_mouse_scroll_not_allowed"

        action: dict[str, Any] = {
            "type": "game_step_action",
            "id": "control",
            "duration_ms": next(iter(durations)),
        }
        if held:
            action["key_hold"] = list(held)
        if tapped:
            action["key_tap"] = list(tapped)
        if move is not None:
            action["mouse"] = dict(move)
        if click is not None:
            action["mouse_click"] = {"button": click}
        if hold is not None:
            action["mouse_hold"] = {"button": hold}
        if scroll is not None:
            action["scroll"] = {"dx": 0, "dy": -200 if scroll == "up" else 200}
        action["unified_action_tool"] = "control"
        return action, None

    def decode_generation(
        self,
        *,
        text: str = "",
        reasoning: str | None = None,
        tool_calls: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        """Reconstruct the exact decoded stream from native or textual output."""

        if not tool_calls:
            thought = str(reasoning or "").strip()
            content = str(text or "").strip()
            if thought and content:
                return f"{thought}\n</think>\n\n{content}"
            if thought:
                return f"{thought}\n</think>"
            return content
        normalized: list[dict[str, Any]] = []
        for raw in tool_calls:
            function = raw.get("function")
            source = function if isinstance(function, Mapping) else raw
            name = source.get("name")
            arguments = source.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments, object_pairs_hook=_strict_object)
                except (json.JSONDecodeError, _DuplicateJSONObjectMemberError):
                    arguments = None
            if not isinstance(name, str) or not isinstance(arguments, Mapping):
                return "\n".join(json.dumps(call, sort_keys=True) for call in tool_calls)
            normalized.append({"tool_name": name, "arguments": dict(arguments)})
        names = [call["tool_name"] for call in normalized]
        if names == ["wait"]:
            frame_calls = normalized if not normalized[0]["arguments"] else []
        elif (
            "wait" not in names
            and len(names) <= 2
            and len(set(names)) == len(names)
            and set(names) <= {"mouse_control", "key_control"}
        ):
            by_name = {call["tool_name"]: call for call in normalized}
            frame_calls = [by_name[name] for name in ("mouse_control", "key_control") if name in by_name]
        else:
            frame_calls = []
        if not frame_calls:
            action = "\n".join(json.dumps(call, sort_keys=True) for call in tool_calls)
        else:
            action = self.render_action_frame({"action_space_mode": "control_v0_5", "tool_calls": frame_calls})
        thought = str(reasoning or "").strip()
        content = str(text or "").strip()
        prefix = thought + ("\n</think>" if thought else "")
        if content:
            prefix += ("\n\n" if prefix else "") + content
        return f"{prefix}\n\n{action}" if prefix else action

    def propose(
        self,
        request: GameGymAgentRequest,
        decoded_output: str,
        *,
        finish_reason: str | None = None,
        reached_generation_limit: bool = False,
    ) -> GameGymAgentProposal:
        if request is not self._pending_request:
            raise RuntimeError("GameWorld model request is stale")
        parsed = _parse_control_frame(decoded_output)
        frame = parsed[0] if parsed is not None else None
        action_span = parsed[1] if parsed is not None else None
        block_count = len(_TOOL_BLOCK_PATTERN.findall(decoded_output))
        invalid_reason = None
        if frame is None:
            invalid_reason = "malformed_action_block" if block_count else "no_valid_action"
        elif action_span is not None:
            prefix = decoded_output[: action_span[0]]
            think_close = _THINK_CLOSE_PATTERN.search(prefix)
            if think_close is not None and prefix[think_close.end() :].strip():
                invalid_reason = "malformed_action_block"
        requested_action = None
        if frame is not None:
            requested_action, mapping_error = self._validate_and_compile(frame)
            if invalid_reason is None and mapping_error is not None:
                invalid_reason = mapping_error
        if finish_reason == "length" and frame is None:
            reached_generation_limit = True
            invalid_reason = "generation_truncated"
        del reached_generation_limit  # retained in the caller's raw generation trace
        valid = requested_action is not None and invalid_reason is None
        if not valid:
            requested_action = _clone(self.fallback_action)
        assert isinstance(requested_action, dict)
        canonical_action = (
            self.render_action_frame(frame)
            if valid and frame is not None
            else self._render_call({"tool_name": str(requested_action.get("id") or "wait"), "arguments": {}})
        )
        canonical_think_action = None
        if valid and action_span is not None:
            canonical_think_action = _canonicalize_think_action(
                decoded_output,
                action_span=action_span,
                canonical_action=canonical_action,
            )
        proposal = GameGymAgentProposal(
            decoded_output=decoded_output,
            parsed_payload=_clone(frame) if frame is not None else None,
            requested_action=requested_action,
            model_action_valid=valid,
            invalid_reason=None if valid else (invalid_reason or "invalid_action"),
            fallback_used=not valid,
            action_span=action_span,
            canonical_action=canonical_action,
            canonical_think_action=canonical_think_action,
        )
        self._pending_proposal = proposal
        return proposal

    def commit(
        self,
        proposal: GameGymAgentProposal,
        *,
        executed_action: Mapping[str, Any],
    ) -> None:
        """Commit history only after GameWorld reports successful execution."""

        if proposal is not self._pending_proposal or self._pending_observation is None:
            raise RuntimeError("GameWorld model proposal is stale")
        if _clone(executed_action) != proposal.requested_action:
            raise ValueError("Executed GameWorld action does not match the model proposal")
        committed_observation = self._pending_observation
        committed_turn = _HistoryTurn(
            observation=committed_observation,
            canonical_action=proposal.canonical_action,
            canonical_think_action=proposal.canonical_think_action,
        )
        self._history.append(committed_turn)
        self._clear_pending()
        protected = (
            [turn.observation for turn in self._history[-self.history_context_turns :]]
            if self._image_retention.retained_turns
            else []
        )
        self._image_retention.track_and_prune(
            committed_observation,
            protected_observations=protected,
        )


__all__ = [
    "COLLAPSED_IMAGE_PLACEHOLDER",
    "GameGymAgent",
    "GameGymAgentProposal",
    "GameGymAgentRequest",
]
