"""Shared memory helpers for model clients."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Literal


MemoryFormat = Literal["ttt", "vvv", "vtvtvt"]
MemoryType = Literal["text", "image"]
MemoryRole = Literal["user", "assistant"]
MemoryField = Literal["user_prompt", "screenshot", "action", "reasoning"]

DEFAULT_MEMORY_FORMAT: MemoryFormat = "vtvtvt"
VALID_MEMORY_FIELDS: frozenset[str] = frozenset(
    {"user_prompt", "screenshot", "action", "reasoning"}
)


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """One memory entry in chronological order."""

    type: MemoryType
    role: MemoryRole
    text: str | None = None
    image_path: str | None = None
    field: str | None = None

    def image_file(self) -> Path | None:
        """Return the image path as a Path when present."""
        if not self.image_path:
            return None
        return Path(self.image_path)


class MemoryStore:
    """Rolling memory buffer grouped by interaction round."""

    def __init__(self, capacity: int = 10) -> None:
        self.capacity = max(0, int(capacity))
        self._memory_rounds: Deque[list[MemoryEntry]] = deque(maxlen=max(self.capacity, 1))

    def add_memory_round(self, entries: Sequence[MemoryEntry]) -> None:
        """Append one round of memory entries."""
        if self.capacity <= 0:
            return
        round_entries = [entry for entry in entries if isinstance(entry, MemoryEntry)]
        if not round_entries:
            return
        self._memory_rounds.append(round_entries)

    def get_recent_memory_rounds(self, limit_rounds: int = 5) -> list[MemoryEntry]:
        """Flatten the most recent rounds into chronological entry order."""
        if limit_rounds <= 0:
            return []
        rounds = list(self._memory_rounds)[-limit_rounds:]
        return [entry for round_entries in rounds for entry in round_entries]


def parse_include_fields(include_fields: Sequence[str] | str | None) -> tuple[str, ...] | None:
    """Normalize include-field configuration into a validated tuple."""
    if include_fields is None:
        return None

    if isinstance(include_fields, str):
        raw_items = [part.strip() for part in include_fields.split(",")]
    else:
        raw_items = [str(part).strip() for part in include_fields]

    fields = [item for item in raw_items if item in VALID_MEMORY_FIELDS]
    if not fields:
        return None
    return tuple(dict.fromkeys(fields))


def _normalize_memory_format(memory_format: str) -> MemoryFormat:
    normalized = str(memory_format or DEFAULT_MEMORY_FORMAT).strip()
    if normalized in {"ttt", "vvv", "vtvtvt"}:
        return normalized  # type: ignore[return-value]
    return DEFAULT_MEMORY_FORMAT


def _filter_memory_entries(
    entries: Sequence[MemoryEntry],
    *,
    memory_format: str,
    include_fields: Sequence[str] | str | None = None,
) -> list[MemoryEntry]:
    selected = [entry for entry in entries if isinstance(entry, MemoryEntry)]
    fields = parse_include_fields(include_fields)
    if fields is not None:
        selected = [entry for entry in selected if entry.field in fields]

    normalized_format = _normalize_memory_format(memory_format)
    if normalized_format == "ttt":
        return [entry for entry in selected if entry.type == "text"]
    if normalized_format == "vvv":
        return [entry for entry in selected if entry.type == "image"]
    return selected


def get_memory_entries(
    memory_store: MemoryStore | None,
    max_rounds: int,
    memory_format: str = DEFAULT_MEMORY_FORMAT,
    include_fields: Sequence[str] | str | None = None,
) -> list[MemoryEntry]:
    """Read filtered memory entries from the store."""
    if memory_store is None or max_rounds <= 0:
        return []
    entries = memory_store.get_recent_memory_rounds(limit_rounds=max_rounds)
    return _filter_memory_entries(
        entries,
        memory_format=memory_format,
        include_fields=include_fields,
    )


def build_memory_round(
    *,
    user_prompt: str | None = "",
    screenshot_path: str | Path | None = "",
    action: str | None = "",
    reasoning: str | None = "",
) -> list[MemoryEntry]:
    """Build one ordered memory round."""
    entries: list[MemoryEntry] = []

    if isinstance(user_prompt, str) and user_prompt.strip():
        entries.append(
            MemoryEntry(
                type="text",
                role="user",
                text=user_prompt,
                field="user_prompt",
            )
        )

    if screenshot_path:
        entries.append(
            MemoryEntry(
                type="image",
                role="user",
                image_path=str(screenshot_path),
                field="screenshot",
            )
        )

    if isinstance(reasoning, str) and reasoning.strip():
        entries.append(
            MemoryEntry(
                type="text",
                role="assistant",
                text=reasoning,
                field="reasoning",
            )
        )

    if isinstance(action, str) and action.strip():
        entries.append(
            MemoryEntry(
                type="text",
                role="assistant",
                text=action,
                field="action",
            )
        )

    return entries


def record_memory_round(
    memory_store: MemoryStore | None,
    user_prompt: str | None = "",
    screenshot_path: str | Path | None = "",
    action: str | None = "",
    reasoning: str | None = "",
) -> None:
    """Append one interaction round to the memory store."""
    if memory_store is None:
        return
    memory_store.add_memory_round(
        build_memory_round(
            user_prompt=user_prompt,
            screenshot_path=screenshot_path,
            action=action,
            reasoning=reasoning,
        )
    )


__all__ = [
    "DEFAULT_MEMORY_FORMAT",
    "MemoryEntry",
    "MemoryStore",
    "build_memory_round",
    "get_memory_entries",
    "parse_include_fields",
    "record_memory_round",
]
