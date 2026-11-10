"""Small, seek-only view of an indexed desktop MCAP session."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Iterable

_MESSAGE_INDEX_OPCODE = 7
_MESSAGE_INDEX_HEADER = struct.Struct("<BQHI")
_MESSAGE_INDEX_ENTRY = struct.Struct("<QQ")


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("desktop MCAP message index is truncated")
    return value


def _message_index_count(stream: BinaryIO, offset: int, expected_channel_id: int) -> int:
    stream.seek(offset)
    opcode, record_length, channel_id, records_length = _MESSAGE_INDEX_HEADER.unpack(
        _read_exact(stream, _MESSAGE_INDEX_HEADER.size)
    )
    if opcode != _MESSAGE_INDEX_OPCODE or channel_id != expected_channel_id:
        raise ValueError("desktop MCAP chunk points to an invalid message index")
    if records_length % _MESSAGE_INDEX_ENTRY.size or record_length != 6 + records_length:
        raise ValueError("desktop MCAP message index has an invalid length")
    return records_length // _MESSAGE_INDEX_ENTRY.size


@dataclass(frozen=True)
class _TopicIndex:
    topic: str
    channel_id: int
    offset: int
    count: int


@dataclass(frozen=True)
class _ChunkIndex:
    start_ns: int
    end_ns: int
    topics: tuple[_TopicIndex, ...]


@dataclass(frozen=True)
class DesktopMcapSessionIndex:
    """Compact chunk counts plus on-demand timestamp lookup.

    MCAP already stores one timestamp/offset message index per channel and
    chunk.  This view keeps only the counts and offsets in memory; boundary
    lookups seek directly into the relevant native index records.
    """

    path: Path
    chunks: tuple[_ChunkIndex, ...]

    def topic_count(self, topic: str) -> int:
        return sum(index.count for chunk in self.chunks for index in chunk.topics if index.topic == topic)

    def first_timestamp(self, topics: Iterable[str]) -> int | None:
        requested = frozenset(topics)
        indexes = [index for chunk in self.chunks for index in chunk.topics if index.topic in requested and index.count]
        if not indexes:
            return None
        with self.path.open("rb") as stream:
            return min(self._timestamp_at(stream, index, 0) for index in indexes)

    def count_before(self, topics: Iterable[str], timestamp_ns: int) -> int:
        """Count requested messages with log time strictly below ``timestamp_ns``."""

        requested = frozenset(topics)
        total = 0
        partial: list[_TopicIndex] = []
        for chunk in self.chunks:
            indexes = [index for index in chunk.topics if index.topic in requested]
            if chunk.end_ns < timestamp_ns:
                total += sum(index.count for index in indexes)
            elif chunk.start_ns < timestamp_ns:
                partial.extend(indexes)
        if not partial:
            return total
        with self.path.open("rb") as stream:
            return total + sum(self._count_index_before(stream, index, timestamp_ns) for index in partial)

    @staticmethod
    def _timestamp_at(stream: BinaryIO, index: _TopicIndex, position: int) -> int:
        stream.seek(index.offset + _MESSAGE_INDEX_HEADER.size + position * _MESSAGE_INDEX_ENTRY.size)
        timestamp_ns, _ = _MESSAGE_INDEX_ENTRY.unpack(_read_exact(stream, _MESSAGE_INDEX_ENTRY.size))
        return timestamp_ns

    @classmethod
    def _count_index_before(cls, stream: BinaryIO, index: _TopicIndex, timestamp_ns: int) -> int:
        low = 0
        high = index.count
        while low < high:
            middle = (low + high) // 2
            if cls._timestamp_at(stream, index, middle) < timestamp_ns:
                low = middle + 1
            else:
                high = middle
        return low


def desktop_mcap_session_index(path: Path) -> DesktopMcapSessionIndex:
    """Load and process-cache the immutable native MCAP index."""

    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    return _cached_session_index(str(resolved), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=16)
def _cached_session_index(path_value: str, _size: int, _mtime_ns: int) -> DesktopMcapSessionIndex:
    try:
        from mcap.reader import make_reader
    except ImportError as error:  # pragma: no cover - paired with the optional desktop adapter dependency
        raise RuntimeError("desktop MCAP indexing requires the mcap package") from error

    path = Path(path_value)
    with path.open("rb") as stream:
        summary = make_reader(stream).get_summary()
        if summary is None or not summary.chunk_indexes:
            raise ValueError(f"desktop MCAP requires native chunk indexes for bounded reads: {path}")
        channel_topics = {channel_id: channel.topic for channel_id, channel in summary.channels.items()}
        chunks: list[_ChunkIndex] = []
        for chunk in summary.chunk_indexes:
            topic_indexes: list[_TopicIndex] = []
            for channel_id, offset in chunk.message_index_offsets.items():
                topic = channel_topics.get(channel_id)
                if topic is None:
                    raise ValueError("desktop MCAP message index names an unknown channel")
                topic_indexes.append(
                    _TopicIndex(
                        topic=topic,
                        channel_id=channel_id,
                        offset=offset,
                        count=_message_index_count(stream, offset, channel_id),
                    )
                )
            chunks.append(
                _ChunkIndex(
                    start_ns=int(chunk.message_start_time),
                    end_ns=int(chunk.message_end_time),
                    topics=tuple(topic_indexes),
                )
            )
    return DesktopMcapSessionIndex(path=path, chunks=tuple(chunks))
