"""Wire contract for compact Player-1 Control releases, shared by producer and reader.

Input adaptation and artifact I/O belong to the callers. The producer and consumers share one dataset schema and history contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from numbers import Integral
from typing import Any

from jsonschema import Draft202012Validator

from player1.agents.actions.parser import PlayerOneActionParser
from player1.agents.actions.serialization import ACTION_FORMAT_QWEN3_CODER_XML
from player1.agents.prompting import DEFAULT_ACTION_PROMPT_TEXT, GAME_AGENT_SYSTEM_PROMPT
from player1.datasets.paths import is_canonical_relative_posix_path
from player1.datasets.player1_control import (
    ACTION_SPACE_MODE,
    player1_control_runtime_tools,
    validate_player1_control_arguments,
)

PARQUET_SCHEMA_VERSION = "player1.dataset.row"
DATA_PRODUCTION_ANNOTATION_PROCEDURE = "player1.reasoning"
IMAGE_CONTRACT_SCHEMA = "player1.dataset.image_reference"
RELEASE_MANIFEST_FILE = "manifest.json"
SPLITS = ("train", "validation")
ROWS_PER_TRAJECTORY = 50
MAX_PARQUET_ROW_GROUP_ROWS = ROWS_PER_TRAJECTORY
PATH_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "sample_id",
        "source_key",
        "source_weight",
        "messages",
        "images",
        "segment_turn_index",
        "canonical_action",
    }
)
IMAGE_REFERENCE_FIELDS = frozenset({"image", "size_bytes"})
_RELEASE_MEMBERS = frozenset({RELEASE_MANIFEST_FILE, *(f"{split}.parquet" for split in SPLITS)})
_RUNTIME_TOOLS = player1_control_runtime_tools()
_ACTION_PARSER = PlayerOneActionParser(
    ACTION_FORMAT_QWEN3_CODER_XML,
    action_space_mode=ACTION_SPACE_MODE,
    runtime_tool_specs=_RUNTIME_TOOLS,
)
_ACTION_SCHEMAS = {tool["id"]: tool["argument_schema"] for tool in _RUNTIME_TOOLS}
_ACTION_VALIDATORS = {name: Draft202012Validator(schema) for name, schema in _ACTION_SCHEMAS.items()}
_HISTORY_PROJECTION = {
    "assembly": "dataset_getitem",
    "recent": {"turns": 3, "mode": "v_a", "observation": "t0_only"},
    "old": {"turns": 3, "mode": "a", "observation": "collapsed"},
    "prefix_policy": "available",
    "segment_history": "contiguous_source_turns_only",
    "historical_assistant": "canonical_action_only",
    "assistant_loss_scope": "current_only",
    "in_context_example_scope": "trajectory",
    "mature_row": {"messages": 16, "images": 4},
}


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty stripped text")
    return value


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return int(value)


def _positive_weight(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a positive finite number")
    weight = float(value)
    if not math.isfinite(weight) or weight <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return weight


def _canonical_action(value: Any, *, sample_id: str) -> str:
    action = _text(value, field="canonical_action")
    frame = _ACTION_PARSER.parse_action_frame(action)
    calls = frame.get("tool_calls") if frame is not None else None
    arguments = {
        call["tool_name"]: call["arguments"] for call in calls or [] if call.get("tool_name") in _ACTION_SCHEMAS
    }
    valid_arguments = (
        isinstance(calls, list)
        and len(arguments) == len(calls)
        and all(_ACTION_VALIDATORS[name].is_valid(value) for name, value in arguments.items())
        and not validate_player1_control_arguments(arguments)
    )
    if frame is None or _ACTION_PARSER.render_action_frame(frame) != action or not valid_arguments:
        raise ValueError(f"Player-1 Control row {sample_id} canonical_action is not canonical")
    return action


def canonical_image_contract() -> dict[str, str]:
    return {
        "schema_version": IMAGE_CONTRACT_SCHEMA,
        "path_basis": "canonical_root_relative",
        "transport": "path_and_size",
    }


def validate_canonical_image_contract(value: Any) -> dict[str, str]:
    expected = canonical_image_contract()
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise ValueError("Player-1 Control image contract is invalid")
    return expected


def player1_control_history_projection_contract() -> dict[str, Any]:
    """Return the published release's history contract; training may reproject compact rows."""

    return deepcopy(_HISTORY_PROJECTION)


def _messages(value: Any, *, sample_id: str, canonical_action: str) -> list[dict[str, str]]:
    raw = value
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError(f"Player-1 Control row {sample_id} must store exactly four current-turn messages")
    messages: list[dict[str, str]] = []
    expected_roles = ("system", "user", "user", "assistant")
    for index, (message, role) in enumerate(zip(raw, expected_roles, strict=True)):
        if not isinstance(message, Mapping) or set(message) != {"role", "content"} or message.get("role") != role:
            raise ValueError(f"Player-1 Control row {sample_id} messages[{index}] is invalid")
        messages.append({"role": role, "content": _text(message.get("content"), field=f"messages[{index}].content")})
    if messages[0]["content"] != GAME_AGENT_SYSTEM_PROMPT:
        raise ValueError(f"Player-1 Control row {sample_id} changed the shared system prompt")
    if "<image>" in messages[1]["content"] or "<video>" in messages[1]["content"]:
        raise ValueError(f"Player-1 Control row {sample_id} initial prompt contains a reserved media token")
    if messages[2]["content"] != f"<image>\n{DEFAULT_ACTION_PROMPT_TEXT}":
        raise ValueError(f"Player-1 Control row {sample_id} changed the current observation prompt")
    prefix, separator = "<think>\n", "\n</think>\n\n"
    assistant = messages[3]["content"]
    if not assistant.startswith(prefix) or separator not in assistant:
        raise ValueError(f"Player-1 Control row {sample_id} assistant is not canonical thinking plus action")
    thinking, action = assistant[len(prefix) :].split(separator, 1)
    if not thinking.strip() or thinking != thinking.strip() or action != canonical_action:
        raise ValueError(f"Player-1 Control row {sample_id} assistant differs from its canonical action")
    if any(marker in thinking.lower() for marker in ("<think", "</think", "<tool_call", "</tool_call")):
        raise ValueError(f"Player-1 Control row {sample_id} thinking contains reserved markup")
    return messages


def _image(value: Any, *, sample_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
        raise ValueError(f"Player-1 Control row {sample_id} must store exactly one current t0 image")
    raw = value[0]
    if set(raw) != IMAGE_REFERENCE_FIELDS:
        raise ValueError(f"Player-1 Control row {sample_id} image is invalid")
    relative = _text(raw.get("image"), field="image.image")
    if not is_canonical_relative_posix_path(relative):
        raise ValueError("image.image must be a canonical relative POSIX path")
    size = _nonnegative_int(raw.get("size_bytes"), field="image.size_bytes")
    if size <= 0:
        raise ValueError(f"Player-1 Control row {sample_id} image size must be positive")
    return [{"image": relative, "size_bytes": size}]


@dataclass(frozen=True, slots=True)
class ValidatedPlayerOneControlPathRecord:
    schema_version: str
    sample_id: str
    source_key: str
    source_weight: float
    messages: list[dict[str, str]]
    images: list[dict[str, Any]]
    segment_turn_index: int
    canonical_action: str


def validate_player1_control_path_record(value: Mapping[str, Any]) -> ValidatedPlayerOneControlPathRecord:
    """Validate one compact current-turn row."""

    record = value
    if not isinstance(record, Mapping) or set(record) != PATH_RECORD_FIELDS:
        raise ValueError("Player-1 Control Parquet row fields do not match the training schema")
    sample_id = _text(record.get("sample_id"), field="sample_id")
    if record.get("schema_version") != PARQUET_SCHEMA_VERSION:
        raise ValueError(f"Player-1 Control row {sample_id} uses an unsupported training schema")
    canonical_action = _canonical_action(record.get("canonical_action"), sample_id=sample_id)
    return ValidatedPlayerOneControlPathRecord(
        schema_version=PARQUET_SCHEMA_VERSION,
        sample_id=sample_id,
        source_key=_text(record.get("source_key"), field="source_key"),
        source_weight=_positive_weight(record.get("source_weight"), field="source_weight"),
        messages=_messages(record.get("messages"), sample_id=sample_id, canonical_action=canonical_action),
        images=_image(record.get("images"), sample_id=sample_id),
        segment_turn_index=_nonnegative_int(record.get("segment_turn_index"), field="segment_turn_index"),
        canonical_action=canonical_action,
    )


def player1_control_parquet_schema() -> Any:
    import pyarrow as pa

    return pa.schema(
        [
            ("schema_version", pa.string()),
            ("sample_id", pa.string()),
            ("source_key", pa.string()),
            ("source_weight", pa.float64()),
            ("messages", pa.list_(pa.struct([("role", pa.string()), ("content", pa.string())]))),
            ("images", pa.list_(pa.struct([("image", pa.string()), ("size_bytes", pa.int64())]))),
            ("segment_turn_index", pa.int64()),
            ("canonical_action", pa.string()),
        ]
    )


def validate_image_reference(value: Any) -> tuple[str, int]:
    if not isinstance(value, Mapping) or set(value) != IMAGE_REFERENCE_FIELDS:
        raise ValueError("Player-1 Control image reference has an invalid shape")
    relative = _text(value.get("image"), field="image reference path")
    if not is_canonical_relative_posix_path(relative):
        raise ValueError("image reference path must be a canonical relative POSIX path")
    size = _nonnegative_int(value.get("size_bytes"), field="image reference size_bytes")
    if size <= 0:
        raise ValueError("image reference size_bytes must be positive")
    return relative, size
