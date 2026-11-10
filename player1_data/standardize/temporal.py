"""Project source-time intervals onto fixed full-frame actions."""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from player1.datasets.player1_control import PLAYER1_CONTROL_DURATION_MS

ANCHOR_INTERVAL_ONSET_OWNER = "anchor_interval"
OnsetOwnerPolicy = Literal["anchor_interval"]

SOURCE_ACTION_WINDOW_COUNT = 50
SOURCE_ACTION_TARGET_DURATION_NS = PLAYER1_CONTROL_DURATION_MS * 1_000_000
SOURCE_ACTION_MIN_INTERVAL_NS = 150_000_000
SOURCE_ACTION_MAX_INTERVAL_NS = 250_000_000


@dataclass(frozen=True, slots=True)
class SourceActionInterval:
    """One source interval and its fixed-duration target action frame."""

    index: int
    anchor_ns: int
    start_ns: int
    end_ns: int
    target_duration_ns: int

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns

    def project_offset_ns(self, source_offset_ns: int) -> int:
        """Map a relative source offset with deterministic integer rounding."""

        if isinstance(source_offset_ns, bool) or not isinstance(source_offset_ns, int):
            raise TypeError("source_offset_ns must be an integer")
        if not 0 <= source_offset_ns <= self.duration_ns:
            raise ValueError("source_offset_ns is outside the source interval")
        if source_offset_ns == self.duration_ns:
            return self.target_duration_ns
        return (source_offset_ns * self.target_duration_ns + self.duration_ns // 2) // self.duration_ns

    def project_timestamp_ns(self, timestamp_ns: int) -> int:
        """Map an absolute source timestamp to a relative target offset."""

        return self.project_offset_ns(timestamp_ns - self.start_ns)


@dataclass(frozen=True, slots=True)
class SourceActionPartition:
    """A seamless source-time partition for one 50-action trajectory."""

    window_starts_ns: tuple[int, ...]
    intervals: tuple[SourceActionInterval, ...]
    target_duration_ns: int
    onset_owner_policy: OnsetOwnerPolicy

    @property
    def boundaries_ns(self) -> tuple[int, ...]:
        return (self.intervals[0].start_ns, *(interval.end_ns for interval in self.intervals))

    @property
    def coverage_start_ns(self) -> int:
        return self.intervals[0].start_ns

    @property
    def coverage_end_ns(self) -> int:
        return self.intervals[-1].end_ns

    def onset_owner(self, timestamp_ns: int) -> int | None:
        """Return the exactly-one half-open interval owning an onset."""

        index = bisect.bisect_right(self.boundaries_ns, timestamp_ns) - 1
        return index if 0 <= index < len(self.intervals) else None

    def maximum_overlap_full_frame_block(
        self,
        *,
        interval_start_ns: int,
        interval_end_ns: int,
        minimum_frames: int = 0,
    ) -> tuple[int, ...]:
        """Select the consecutive fixed frames with maximum projected overlap."""

        if interval_end_ns <= interval_start_ns:
            return ()
        weights = []
        projected_duration_ns = weighted_position_twice = 0
        for index, source_interval in enumerate(self.intervals):
            start_ns = max(source_interval.start_ns, interval_start_ns)
            end_ns = min(source_interval.end_ns, interval_end_ns)
            if end_ns <= start_ns:
                weights.append(0)
                continue
            target_start = index * self.target_duration_ns + source_interval.project_timestamp_ns(start_ns)
            target_end = index * self.target_duration_ns + source_interval.project_timestamp_ns(end_ns)
            weight = target_end - target_start
            weights.append(weight)
            projected_duration_ns += weight
            weighted_position_twice += (target_start + target_end) * weight
        overlapping = tuple(index for index, weight in enumerate(weights) if weight > 0)
        if not overlapping:
            return ()
        desired = (projected_duration_ns + self.target_duration_ns // 2) // self.target_duration_ns
        count = min(max(minimum_frames, desired), overlapping[-1] - overlapping[0] + 1)
        if count <= 0:
            return ()

        projected_center_twice = weighted_position_twice // projected_duration_ns

        def score(first_index: int) -> tuple[int, int, int]:
            selected = sum(weights[first_index : first_index + count])
            block_center_twice = (2 * first_index + count) * self.target_duration_ns
            return selected, -abs(block_center_twice - projected_center_twice), -first_index

        first = overlapping[0]
        last = overlapping[-1] - count + 1
        best = max(range(first, last + 1), key=score)
        return tuple(range(best, best + count))


def build_source_action_partition(
    window_starts_ns: Sequence[int],
    *,
    onset_owner_policy: OnsetOwnerPolicy = ANCHOR_INTERVAL_ONSET_OWNER,
) -> SourceActionPartition:
    """Build and validate the source-time partition for a 50-action trace."""

    target_duration_ns = SOURCE_ACTION_TARGET_DURATION_NS
    starts = tuple(window_starts_ns)
    if len(starts) != SOURCE_ACTION_WINDOW_COUNT:
        raise ValueError(f"source action partition requires exactly {SOURCE_ACTION_WINDOW_COUNT} window starts")
    if any(isinstance(start, bool) or not isinstance(start, int) for start in starts):
        raise TypeError("source action window starts must be integers")
    if any(left >= right for left, right in zip(starts, starts[1:])):
        raise ValueError("source action window starts must be strictly increasing")
    if onset_owner_policy != ANCHOR_INTERVAL_ONSET_OWNER:
        raise ValueError(f"unsupported onset owner policy: {onset_owner_policy!r}")

    boundaries = (*starts, starts[-1] + target_duration_ns)
    intervals = tuple(
        SourceActionInterval(
            index=index,
            anchor_ns=starts[index],
            start_ns=boundaries[index],
            end_ns=boundaries[index + 1],
            target_duration_ns=target_duration_ns,
        )
        for index in range(len(starts))
    )
    invalid = [
        interval
        for interval in intervals
        if not SOURCE_ACTION_MIN_INTERVAL_NS <= interval.duration_ns <= SOURCE_ACTION_MAX_INTERVAL_NS
    ]
    if invalid:
        detail = ", ".join(f"{interval.index}:{interval.duration_ns}" for interval in invalid[:3])
        raise ValueError(f"source action interval cadence is outside 150-250ms ({detail})")
    return SourceActionPartition(
        window_starts_ns=starts,
        intervals=intervals,
        target_duration_ns=target_duration_ns,
        onset_owner_policy=onset_owner_policy,
    )


__all__ = [
    "ANCHOR_INTERVAL_ONSET_OWNER",
    "SOURCE_ACTION_MAX_INTERVAL_NS",
    "SOURCE_ACTION_MIN_INTERVAL_NS",
    "SOURCE_ACTION_TARGET_DURATION_NS",
    "SOURCE_ACTION_WINDOW_COUNT",
    "OnsetOwnerPolicy",
    "SourceActionInterval",
    "SourceActionPartition",
    "build_source_action_partition",
]
