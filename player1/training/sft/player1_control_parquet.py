"""Bounded-memory access to compact Player-1 Control training rows."""

from __future__ import annotations

import logging
import math
import os
import time
from array import array
from bisect import bisect_right
from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
from numbers import Integral
from pathlib import PurePosixPath
from typing import Any

from player1.agents.history_context import (
    HISTORY_CONTEXT_MESSAGE_METADATA_KEY,
    build_history_context_metadata,
    select_history_context_messages,
)
from player1.agents.prompting import DEFAULT_ACTION_PROMPT_TEXT

from player1.training.sft.player1_control_prompt import project_player1_control_prefix
from player1.datasets.release_contract import ValidatedPlayerOneControlPathRecord, player1_control_parquet_schema
from player1.datasets.release_reader import CanonicalImageStore, validate_player1_control_path_record
from player1.datasets.storage import S3ReleaseFileSnapshot
from player1.training.sft.player1_control_training_contract import (
    PlayerOneControlReleaseFileSnapshot,
    player1_control_training_history,
)
from player1.training.sft.history_context_sampling import HISTORY_CHOICES, HistorySampleIndex

_INITIAL_MESSAGE_COUNT = 2
_LOGGER = logging.getLogger(__name__)
_S3_STREAM_FLUSH_FAILURE = (
    "AWS Error INTERNAL_FAILURE during GetObject operation: Failed to flush response stream"
)


class _RowView:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def to_dict(self) -> dict[str, Any]:
        return self._row


class _ILoc:
    def __init__(self, rows: PlayerOneControlParquetRows) -> None:
        self._rows = rows

    def __getitem__(self, index: int | HistorySampleIndex) -> _RowView:
        return _RowView(self._rows.row(index))


class _ReadOnlyFloat64(Sequence[float]):
    def __init__(self, values: array[float]) -> None:
        self._values = values

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index: int | slice) -> float | array[float]:
        return self._values[index]


def _observation(image: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {"type": "image", "image": image["image"]},
            {"type": "text", "text": DEFAULT_ACTION_PROMPT_TEXT},
        ],
    }


def _flat_message(message: Mapping[str, Any]) -> dict[str, str]:
    role = message.get("role")
    content = message.get("content")
    if not isinstance(role, str):
        raise ValueError("Player-1 Control projected message has no role")
    if isinstance(content, str):
        return {"role": role, "content": content}
    if not isinstance(content, list):
        raise ValueError("Player-1 Control projected message content is invalid")
    pieces: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            raise ValueError("Player-1 Control projected multimodal content is invalid")
        if item.get("type") == "image":
            pieces.append("<image>\n")
        elif item.get("type") == "text" and isinstance(item.get("text"), str):
            pieces.append(item["text"])
        else:
            raise ValueError("Player-1 Control projected multimodal content is invalid")
    return {"role": role, "content": "".join(pieces)}


def _project_row(
    rows: Sequence[ValidatedPlayerOneControlPathRecord],
    index: int,
    *,
    image_store: CanonicalImageStore,
    recent_turns: int,
    old_turns: int,
) -> dict[str, Any]:
    current = rows[index]
    history_count = min(old_turns + recent_turns, current.segment_turn_index, index)
    history = rows[index - history_count : index]
    ledger: list[dict[str, Any]] = project_player1_control_prefix(current.messages[:_INITIAL_MESSAGE_COUNT])
    for record in history:
        ledger.append(_observation(record.images[0]))
        ledger.append(
            {
                "role": "assistant",
                "content": record.canonical_action,
                HISTORY_CONTEXT_MESSAGE_METADATA_KEY: build_history_context_metadata(
                    "v_a",
                    record.canonical_action,
                    replay_source="admitted",
                ),
            }
        )
    ledger.append(_observation(current.images[0]))
    selected, _ = select_history_context_messages(
        messages=ledger,
        initial_prompt_message_count=_INITIAL_MESSAGE_COUNT,
        history_context_turns=recent_turns,
        history_context_mode="v_a",
        history_context_old_turns=old_turns,
        history_context_old_mode="a",
    )
    messages = [_flat_message(message) for message in selected]
    messages.append(deepcopy(current.messages[-1]))
    visual_history = history[-recent_turns:] if recent_turns else []
    images = [record.images[0] for record in visual_history] + current.images
    return {
        "schema_version": current.schema_version,
        "sample_id": current.sample_id,
        "source_key": current.source_key,
        "source_weight": current.source_weight,
        "messages": messages,
        "images": [{"bytes": image_store.read(image)} for image in images],
    }


class PlayerOneControlParquetRows:
    """Expose ``iloc`` while caching at most one complete trajectory."""

    def __init__(
        self,
        snapshot: PlayerOneControlReleaseFileSnapshot | S3ReleaseFileSnapshot,
        *,
        split: str,
        trajectories: Sequence[dict[str, Any]],
        image_store: CanonicalImageStore,
        history_config: Mapping[str, Any] | None = None,
    ) -> None:
        if split not in {"train", "validation"}:
            raise ValueError("Player-1 Control Parquet split must be train or validation")
        if not isinstance(image_store, CanonicalImageStore):
            raise TypeError("Player-1 Control Parquet rows require a canonical image store")
        self.path = snapshot.path
        self.split = split
        self.columns: tuple[str, ...] = ()
        self._snapshot = snapshot
        self._image_store = image_store
        history = player1_control_training_history(history_config or {})
        self._recent_turns = history["recent"]["turns"]
        self._old_turns = history["old"]["turns"]
        self._descriptors = tuple(deepcopy(list(trajectories)))
        self._stops: tuple[int, ...] = ()
        self._counts: tuple[int, ...] = ()
        self._weights = array("d")
        self._reader: Any | None = None
        self._stream: Any | None = None
        self._reader_pid: int | None = None
        self._cached_group: int | None = None
        self._cached_rows: tuple[ValidatedPlayerOneControlPathRecord, ...] = ()
        self._cache_pid: int | None = None
        self._inspect()
        self.iloc = _ILoc(self)

    def _inspect(self) -> None:
        parquet = self._open()
        try:
            self.columns = tuple(parquet.schema_arrow.names)
            if not parquet.schema_arrow.equals(player1_control_parquet_schema()):
                raise ValueError("Player-1 Control Parquet columns do not match the compact schema")
            if parquet.num_row_groups != len(self._descriptors):
                raise ValueError(f"Player-1 Control {self.split} row-group coverage differs from Parquet")
            stops: list[int] = []
            counts: list[int] = []
            total = 0
            for ordinal, descriptor in enumerate(self._descriptors):
                count = parquet.metadata.row_group(ordinal).num_rows
                if (
                    descriptor["split"] != self.split or descriptor["row_group"] != ordinal
                    or count != descriptor["rows"]
                ):
                    raise ValueError(f"Player-1 Control {self.split} row group is not one complete trajectory")
                total += count
                counts.append(count)
                stops.append(total)
            # Weights belong to the rows, not a second copy in the manifest.
            for batch in parquet.iter_batches(columns=["source_weight"], batch_size=8192):
                for weight in batch.column(0).to_pylist():
                    if weight is None or not math.isfinite(weight) or weight <= 0:
                        raise ValueError("Player-1 Control source weights must be positive and finite")
                    self._weights.append(weight)
            if len(self._weights) != total:
                raise ValueError(f"Player-1 Control {self.split} weights differ from its row count")
            self._counts = tuple(counts)
            self._stops = tuple(stops)
            self._snapshot.assert_metadata_current()
        finally:
            self._close_reader()

    @property
    def source_weights(self) -> Sequence[float]:
        return _ReadOnlyFloat64(self._weights)

    @property
    def row_group_stops(self) -> tuple[int, ...]:
        return self._stops

    def __len__(self) -> int:
        return len(self._weights)

    def iter_canonical_actions(self) -> Iterator[str]:
        """Scan only the target-action column for the opt-in balanced sampler."""
        self._snapshot.assert_metadata_current()
        try:
            for batch in self._open().iter_batches(columns=["canonical_action"], batch_size=8192):
                yield from batch.column(0).to_pylist()
            self._snapshot.assert_metadata_current()
        finally:
            self._close_reader()

    def _open(self) -> Any:
        pid = os.getpid()
        if self._reader is not None and self._reader_pid != pid:
            self._close_reader()
        if self._reader is None:
            import pyarrow.parquet as pq

            self._stream = self._snapshot.open_metadata_verified()
            try:
                self._reader = pq.ParquetFile(self._stream)
                self._reader_pid = pid
            except Exception:
                self._stream.close()
                self._stream = None
                raise
        return self._reader

    def _read_group(self, ordinal: int) -> list[dict[str, Any]]:
        for attempt in range(3):
            try:
                self._snapshot.assert_metadata_current()
                return self._open().read_row_group(ordinal).to_pylist()
            except OSError as error:
                if not isinstance(self._snapshot, S3ReleaseFileSnapshot) or _S3_STREAM_FLUSH_FAILURE not in str(error):
                    raise
                # A failed Arrow response stream must not be reused. Reopening
                # also rechecks the frozen ETag/version before the same read.
                self._close_reader()
                if attempt == 2:
                    error.add_note(f"SFT {self.split} row group {ordinal}: S3 stream failed after 3 attempts")
                    raise
                _LOGGER.warning(
                    "SFT %s row group %d: S3 response-stream failure; reopening for retry %d/2",
                    self.split, ordinal, attempt + 1,
                )
                time.sleep(attempt + 1)
        raise AssertionError("Unreachable S3 row-group retry state")

    def _load_group(self, ordinal: int) -> None:
        raw_rows = self._read_group(ordinal)
        if len(raw_rows) != self._counts[ordinal]:
            raise ValueError(f"Player-1 Control {self.split} Parquet row group changed while reading")
        rows = tuple(validate_player1_control_path_record(row) for row in raw_rows)
        first = rows[0]
        descriptor = self._descriptors[ordinal]
        if any(
            PurePosixPath(image["image"]).parts[:2] != ("trajectories", descriptor["id"])
            for row in rows for image in row.images
        ):
            raise ValueError("SFT image differs from trajectory provenance")
        if first.segment_turn_index != 0:
            raise ValueError("Player-1 Control trajectory must start a segment")
        group_start = 0 if ordinal == 0 else self._stops[ordinal - 1]
        for offset, row in enumerate(rows):
            if (
                row.segment_turn_index != offset
                or row.source_key != first.source_key
                or row.source_key != self._descriptors[ordinal]["source"]["adapter_id"]
                or row.source_weight != first.source_weight
                or row.messages[:2] != first.messages[:2]
                or row.source_weight != self._weights[group_start + offset]
            ):
                raise ValueError("Player-1 Control trajectory rows are not contiguous and stable")
        self._snapshot.assert_metadata_current()
        self._cached_group = ordinal
        self._cached_rows = rows
        self._cache_pid = os.getpid()

    def row(self, index: int | HistorySampleIndex) -> dict[str, Any]:
        recent, old = self._recent_turns, self._old_turns
        if isinstance(index, HistorySampleIndex):
            if self.split != "train":
                raise ValueError("Sampled history is only allowed for the training split")
            index, recent, old = index
            if (recent, old) not in HISTORY_CHOICES:
                raise ValueError("Sampled history capacities must be in 0..2")
        if isinstance(index, bool) or not isinstance(index, Integral):
            raise TypeError("Player-1 Control Parquet row index must be an integer")
        normalized = int(index)
        if normalized < 0:
            normalized += len(self)
        if not 0 <= normalized < len(self):
            raise IndexError("Player-1 Control Parquet row index is out of range")
        if self._cache_pid != os.getpid():
            self._cached_group = None
            self._cached_rows = ()
            self._cache_pid = None
        group = bisect_right(self._stops, normalized)
        group_start = 0 if group == 0 else self._stops[group - 1]
        if group != self._cached_group:
            self._load_group(group)
        return _project_row(
            self._cached_rows, normalized - group_start, image_store=self._image_store,
            recent_turns=recent, old_turns=old,
        )

    def _close_reader(self) -> None:
        reader, self._reader = self._reader, None
        stream, self._stream = self._stream, None
        self._reader_pid = None
        if reader is not None:
            reader.close()
        if stream is not None and not stream.closed:
            stream.close()

    def close(self) -> None:
        self._cached_group = None
        self._cached_rows = ()
        self._cache_pid = None
        self._close_reader()

    def __enter__(self) -> PlayerOneControlParquetRows:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state.update(
            _reader=None,
            _stream=None,
            _reader_pid=None,
            _cached_group=None,
            _cached_rows=(),
            _cache_pid=None,
        )
        return state

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


__all__ = ["PlayerOneControlParquetRows"]
