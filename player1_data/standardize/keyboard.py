"""Project source-authoritative keyboard timelines onto Player-1 Control frames."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from player1.agents.actions.devices import STANDARD_KEYBOARD_KEYS
from player1_data.standardize.temporal import (
    ANCHOR_INTERVAL_ONSET_OWNER,
    OnsetOwnerPolicy,
    SourceActionPartition,
)

_DECISION_WINDOW_NS = 200_000_000
_EDGE_RECONCILIATION_TOLERANCE_NS = 10_000_000
_SUPPORTED_KEYS = frozenset(STANDARD_KEYBOARD_KEYS)


class KeyboardGestureError(ValueError):
    """The raw keyboard timeline cannot be represented by Player-1 Control."""

    def __init__(self, message: str, *, reason_code: str, evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.evidence = dict(evidence or {})


@dataclass(frozen=True, order=True)
class KeyboardKey:
    identity: str
    key: str


@dataclass(frozen=True)
class KeyboardState:
    timestamp_ns: int
    source_order: int
    keys: tuple[KeyboardKey, ...]
    transition_exact: bool = False


@dataclass(frozen=True)
class KeyboardEdge:
    timestamp_ns: int
    source_order: int
    identity: str
    key: str
    pressed: bool


@dataclass(frozen=True)
class KeyboardImpulse:
    timestamp_ns: int
    source_order: int
    identity: str
    key: str


@dataclass(frozen=True)
class KeyboardTimeline:
    authority: str
    evidence_kind: Literal["exact_edges", "state_snapshots"]
    window_starts_ns: tuple[int, ...]
    seed: KeyboardState
    checkpoints: tuple[KeyboardState, ...]
    edges: tuple[KeyboardEdge, ...]
    observed_end_ns: int
    impulses: tuple[KeyboardImpulse, ...] = ()
    onset_owner_policy: OnsetOwnerPolicy = ANCHOR_INTERVAL_ONSET_OWNER
    maximum_sample_gap_ns: int | None = None


@dataclass(frozen=True)
class _Gesture:
    identity: str
    key: str
    down_ns: int | None
    up_ns: int | None
    observed_since_ns: int
    down_earliest_ns: int | None
    up_earliest_ns: int | None


def _invalid(message: str, *, evidence: Mapping[str, Any] | None = None) -> KeyboardGestureError:
    return KeyboardGestureError(message, reason_code="keyboard_gesture_evidence_invalid", evidence=evidence)


def _state_map(state: KeyboardState) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in state.keys:
        if not isinstance(item, KeyboardKey) or not item.identity or not item.key:
            raise _invalid("keyboard states must contain non-empty physical identities and canonical keys")
        if item.identity in result:
            raise _invalid("keyboard state repeats one physical identity", evidence={"identity": item.identity})
        result[item.identity] = item.key
    return result


def _validate_timeline(timeline: KeyboardTimeline, partition: SourceActionPartition) -> None:
    if not isinstance(timeline.authority, str) or not timeline.authority:
        raise _invalid("keyboard authority must be non-empty text")
    if timeline.evidence_kind not in {"exact_edges", "state_snapshots"}:
        raise _invalid("keyboard evidence kind is unsupported")
    if (
        timeline.window_starts_ns != partition.window_starts_ns
        or timeline.onset_owner_policy != partition.onset_owner_policy
        or partition.target_duration_ns != _DECISION_WINDOW_NS
    ):
        raise _invalid("keyboard timeline differs from its recording partition")
    if timeline.maximum_sample_gap_ns is not None and (
        isinstance(timeline.maximum_sample_gap_ns, bool)
        or not isinstance(timeline.maximum_sample_gap_ns, int)
        or timeline.maximum_sample_gap_ns <= 0
    ):
        raise _invalid("keyboard maximum sample gap must be positive integer nanoseconds")
    if timeline.evidence_kind == "exact_edges" and timeline.maximum_sample_gap_ns is not None:
        raise _invalid("exact-edge keyboard evidence cannot declare a sample-gap bound")
    if timeline.evidence_kind == "state_snapshots" and timeline.maximum_sample_gap_ns is None:
        raise _invalid("state-snapshot keyboard evidence requires a maximum sample gap")
    starts = timeline.window_starts_ns
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (timeline.seed.timestamp_ns, timeline.seed.source_order, timeline.observed_end_ns)
    ):
        raise _invalid("keyboard timeline times and source orders must be integers")
    if timeline.seed.timestamp_ns > starts[0] or timeline.observed_end_ns < starts[-1] + _DECISION_WINDOW_NS:
        raise _invalid("keyboard evidence does not cover the decision sequence")
    _state_map(timeline.seed)

    records: list[KeyboardState | KeyboardEdge | KeyboardImpulse] = [
        *timeline.checkpoints,
        *timeline.edges,
        *timeline.impulses,
    ]
    for record in records:
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (record.timestamp_ns, record.source_order)
        ):
            raise _invalid("keyboard records must use integer times and source orders")
        if not timeline.seed.timestamp_ns <= record.timestamp_ns <= timeline.observed_end_ns:
            raise _invalid("keyboard record falls outside the observed interval")
        if record.source_order <= timeline.seed.source_order:
            raise _invalid("keyboard record source order must follow the seed")
        if isinstance(record, KeyboardState):
            _state_map(record)
        else:
            if not record.identity or not record.key:
                raise _invalid("keyboard edges and impulses require identity and key")
            if isinstance(record, KeyboardEdge) and not isinstance(record.pressed, bool):
                raise _invalid("keyboard edge pressed must be boolean")
    if timeline.evidence_kind == "state_snapshots" and timeline.edges:
        raise _invalid("state-snapshot keyboard timelines cannot also carry authoritative edges")

    ordered = sorted(records, key=lambda record: (record.timestamp_ns, record.source_order))
    if records and len({record.source_order for record in records}) != len(records):
        raise _invalid("keyboard records repeat a source order")
    if any(
        (right.timestamp_ns, right.source_order) <= (left.timestamp_ns, left.source_order)
        for left, right in zip(ordered, ordered[1:], strict=False)
    ):
        raise _invalid("keyboard records do not preserve source-time order")
    if timeline.evidence_kind == "state_snapshots":
        assert timeline.maximum_sample_gap_ns is not None
        samples = [
            timeline.seed,
            *sorted(timeline.checkpoints, key=lambda item: (item.timestamp_ns, item.source_order)),
        ]
        sample_times = [sample.timestamp_ns for sample in samples]
        sample_times.append(timeline.observed_end_ns)
        for sample_index, (left, right) in enumerate(zip(sample_times, sample_times[1:], strict=False)):
            if right - left > timeline.maximum_sample_gap_ns:
                raise KeyboardGestureError(
                    "keyboard state-snapshot cadence exceeds its source certainty bound",
                    reason_code="keyboard_gesture_sample_gap_invalid",
                    evidence={
                        "sample_index": sample_index,
                        "gap_ns": right - left,
                        "maximum_sample_gap_ns": timeline.maximum_sample_gap_ns,
                    },
                )


def _close_gesture(
    gestures: list[_Gesture],
    *,
    identity: str,
    key: str,
    down_ns: int | None,
    up_ns: int,
    observed_since_ns: int,
    down_earliest_ns: int | None,
    up_earliest_ns: int,
) -> None:
    gestures.append(
        _Gesture(
            identity=identity,
            key=key,
            down_ns=down_ns,
            up_ns=up_ns,
            observed_since_ns=observed_since_ns,
            down_earliest_ns=down_earliest_ns,
            up_earliest_ns=up_earliest_ns,
        )
    )


def _checkpoint_matches_nearby_edge(
    state: KeyboardState,
    active: Mapping[str, str],
    edges: tuple[KeyboardEdge, ...],
    *,
    identities: set[str] | None = None,
) -> bool:
    observed = _state_map(state)
    expected = dict(active)
    if identities is not None:
        observed = {identity: key for identity, key in observed.items() if identity in identities}
        expected = {identity: key for identity, key in expected.items() if identity in identities}
    for edge in edges:
        if identities is not None and edge.identity not in identities:
            continue
        if abs(edge.timestamp_ns - state.timestamp_ns) > _EDGE_RECONCILIATION_TOLERANCE_NS:
            continue
        alternative = dict(expected)
        if edge.source_order < state.source_order:
            if edge.pressed:
                alternative.pop(edge.identity, None)
            else:
                alternative[edge.identity] = edge.key
        elif edge.pressed:
            alternative[edge.identity] = edge.key
        else:
            alternative.pop(edge.identity, None)
        if observed == alternative:
            return True
    return False


def _pair_gestures(timeline: KeyboardTimeline) -> list[_Gesture]:
    active = _state_map(timeline.seed)
    down_edges: dict[str, int | None] = {identity: None for identity in active}
    down_earliest: dict[str, int | None] = {identity: None for identity in active}
    observed_since = {identity: timeline.seed.timestamp_ns for identity in active}
    gestures: list[_Gesture] = []

    if timeline.evidence_kind == "state_snapshots":
        previous_timestamp_ns = timeline.seed.timestamp_ns
        for state in sorted(timeline.checkpoints, key=lambda item: (item.timestamp_ns, item.source_order)):
            next_active = _state_map(state)
            changed = {
                identity for identity in active.keys() & next_active.keys() if active[identity] != next_active[identity]
            }
            if changed:
                raise _invalid("one keyboard identity changed canonical key", evidence={"identities": sorted(changed)})
            for identity in sorted(active.keys() - next_active.keys()):
                _close_gesture(
                    gestures,
                    identity=identity,
                    key=active[identity],
                    down_ns=down_edges.pop(identity),
                    up_ns=state.timestamp_ns,
                    observed_since_ns=observed_since.pop(identity),
                    down_earliest_ns=down_earliest.pop(identity),
                    up_earliest_ns=(state.timestamp_ns if state.transition_exact else previous_timestamp_ns),
                )
            for identity in sorted(next_active.keys() - active.keys()):
                down_edges[identity] = state.timestamp_ns
                down_earliest[identity] = state.timestamp_ns if state.transition_exact else previous_timestamp_ns
                observed_since[identity] = state.timestamp_ns
            active = next_active
            previous_timestamp_ns = state.timestamp_ns
    else:
        records: list[KeyboardState | KeyboardEdge] = [*timeline.checkpoints, *timeline.edges]
        records.sort(key=lambda item: item.source_order)
        previous_order = timeline.seed.source_order
        previous_timestamp = timeline.seed.timestamp_ns
        coverage_end_ns = timeline.window_starts_ns[-1] + _DECISION_WINDOW_NS
        closure_identities: set[str] | None = None
        for record in records:
            if record.source_order <= previous_order or record.timestamp_ns < previous_timestamp:
                raise _invalid("keyboard exact evidence does not preserve source order")
            previous_order = record.source_order
            previous_timestamp = record.timestamp_ns
            if record.timestamp_ns >= coverage_end_ns and closure_identities is None:
                closure_identities = set(active)
            if isinstance(record, KeyboardState):
                checkpoint = _state_map(record)
                compared_identities = (
                    closure_identities if closure_identities is not None else set(active) | set(checkpoint)
                )
                expected = {identity: active[identity] for identity in compared_identities if identity in active}
                observed = {
                    identity: checkpoint[identity] for identity in compared_identities if identity in checkpoint
                }
                if observed != expected and not _checkpoint_matches_nearby_edge(
                    record,
                    active,
                    timeline.edges,
                    identities=compared_identities,
                ):
                    raise KeyboardGestureError(
                        "keyboard edges disagree with a state checkpoint",
                        reason_code="keyboard_gesture_state_mismatch",
                        evidence={
                            "timestamp_ns": record.timestamp_ns,
                            "edge_state": sorted(expected.items()),
                            "checkpoint_state": sorted(observed.items()),
                        },
                    )
                continue
            if closure_identities is not None and record.identity not in closure_identities:
                continue
            if record.pressed:
                if record.identity in active:
                    if active[record.identity] != record.key:
                        raise _invalid("keyboard repeat changed canonical key", evidence={"identity": record.identity})
                    continue
                active[record.identity] = record.key
                down_edges[record.identity] = record.timestamp_ns
                down_earliest[record.identity] = record.timestamp_ns
                observed_since[record.identity] = record.timestamp_ns
                continue
            if active.get(record.identity) != record.key:
                raise KeyboardGestureError(
                    "keyboard release has no matching active physical key",
                    reason_code="keyboard_gesture_orphan_release",
                    evidence={"identity": record.identity, "key": record.key, "timestamp_ns": record.timestamp_ns},
                )
            _close_gesture(
                gestures,
                identity=record.identity,
                key=record.key,
                down_ns=down_edges.pop(record.identity),
                up_ns=record.timestamp_ns,
                observed_since_ns=observed_since.pop(record.identity),
                down_earliest_ns=down_earliest.pop(record.identity),
                up_earliest_ns=record.timestamp_ns,
            )
            del active[record.identity]
            if closure_identities is not None:
                closure_identities.discard(record.identity)

    gestures.extend(
        _Gesture(
            identity=identity,
            key=key,
            down_ns=down_edges[identity],
            up_ns=None,
            observed_since_ns=observed_since[identity],
            down_earliest_ns=down_earliest[identity],
            up_earliest_ns=None,
        )
        for identity, key in sorted(active.items())
    )
    return gestures


def _intersects(gesture: _Gesture, coverage_start_ns: int, coverage_end_ns: int) -> bool:
    return (gesture.up_ns is None or gesture.up_ns > coverage_start_ns) and (
        gesture.down_ns is None or gesture.down_ns < coverage_end_ns
    )


def _duration_bounds(gesture: _Gesture) -> tuple[int, int] | None:
    if (
        gesture.down_ns is None
        or gesture.up_ns is None
        or gesture.down_earliest_ns is None
        or gesture.up_earliest_ns is None
    ):
        return None
    return (
        max(0, gesture.up_earliest_ns - gesture.down_ns),
        gesture.up_ns - gesture.down_earliest_ns,
    )


def _unique_onset_owner(
    gesture: _Gesture,
    partition: SourceActionPartition,
) -> int | None:
    assert gesture.down_ns is not None and gesture.down_earliest_ns is not None
    candidates = {partition.onset_owner(timestamp_ns) for timestamp_ns in {gesture.down_earliest_ns, gesture.down_ns}}
    if len(candidates) != 1:
        raise KeyboardGestureError(
            "keyboard onset uncertainty crosses a decision boundary",
            reason_code="keyboard_gesture_quantized_ambiguous",
            evidence={
                "identity": gesture.identity,
                "key": gesture.key,
                "down_earliest_ns": gesture.down_earliest_ns,
                "down_latest_ns": gesture.down_ns,
            },
        )
    return candidates.pop()


def _unique_hold_block(
    gesture: _Gesture,
    partition: SourceActionPartition,
    observed_end_ns: int,
) -> tuple[int, ...]:
    interval_starts = (
        {gesture.observed_since_ns} if gesture.down_ns is None else {gesture.down_earliest_ns, gesture.down_ns}
    )
    interval_ends = {observed_end_ns} if gesture.up_ns is None else {gesture.up_earliest_ns, gesture.up_ns}
    assert None not in interval_starts and None not in interval_ends
    blocks = {
        partition.maximum_overlap_full_frame_block(
            interval_start_ns=int(interval_start_ns),
            interval_end_ns=int(interval_end_ns),
        )
        for interval_start_ns in interval_starts
        for interval_end_ns in interval_ends
    }
    if len(blocks) != 1:
        raise KeyboardGestureError(
            "keyboard state-snapshot uncertainty changes the projected hold frames",
            reason_code="keyboard_gesture_quantized_ambiguous",
            evidence={"identity": gesture.identity, "key": gesture.key},
        )
    return blocks.pop()


def project_keyboard_timeline(timeline: KeyboardTimeline, partition: SourceActionPartition) -> list[dict[str, Any]]:
    """Replay a raw timeline once and emit one keyboard action per decision frame."""

    _validate_timeline(timeline, partition)
    starts = partition.window_starts_ns
    coverage_start_ns = partition.coverage_start_ns
    coverage_end_ns = partition.coverage_end_ns
    tap_counts: list[dict[str, int]] = [{} for _ in starts]
    hold_counts: list[dict[str, int]] = [{} for _ in starts]

    for gesture in _pair_gestures(timeline):
        if not _intersects(gesture, coverage_start_ns, coverage_end_ns):
            continue
        if gesture.key not in _SUPPORTED_KEYS:
            raise KeyboardGestureError(
                "keyboard gesture uses a key outside Player-1 Control",
                reason_code="unsupported_keyboard_action",
                evidence={"identity": gesture.identity, "key": gesture.key},
            )
        duration_bounds = _duration_bounds(gesture)
        # This boundary comes from nearest-frame quantization, not a claim
        # about the key's game-specific intent. Half-frame ties become one hold.
        if duration_bounds is not None and duration_bounds[1] < _DECISION_WINDOW_NS // 2:
            owner = _unique_onset_owner(
                gesture,
                partition,
            )
            if owner is not None:
                tap_counts[owner][gesture.key] = tap_counts[owner].get(gesture.key, 0) + 1
            continue
        if duration_bounds is not None and duration_bounds[0] < _DECISION_WINDOW_NS // 2:
            raise KeyboardGestureError(
                "keyboard state-snapshot duration crosses the tap/hold boundary",
                reason_code="keyboard_gesture_quantized_ambiguous",
                evidence={
                    "identity": gesture.identity,
                    "key": gesture.key,
                    "minimum_duration_ns": duration_bounds[0],
                    "maximum_duration_ns": duration_bounds[1],
                },
            )
        if gesture.down_ns is not None and gesture.up_ns is None:
            if timeline.observed_end_ns - gesture.down_ns < _DECISION_WINDOW_NS // 2:
                raise KeyboardGestureError(
                    "right-censored keyboard gesture is too short to classify",
                    reason_code="keyboard_gesture_censored_ambiguous",
                    evidence={"identity": gesture.identity, "key": gesture.key},
                )
        if gesture.down_ns is None and gesture.up_ns is not None:
            if gesture.up_ns - gesture.observed_since_ns < _DECISION_WINDOW_NS // 2:
                raise KeyboardGestureError(
                    "left-censored keyboard gesture is too short to classify",
                    reason_code="keyboard_gesture_censored_ambiguous",
                    evidence={"identity": gesture.identity, "key": gesture.key},
                )
        for window_index in _unique_hold_block(
            gesture,
            partition,
            timeline.observed_end_ns,
        ):
            if not coverage_start_ns <= starts[window_index] < coverage_end_ns:
                continue
            hold_counts[window_index][gesture.key] = hold_counts[window_index].get(gesture.key, 0) + 1

    for impulse in timeline.impulses:
        if impulse.key not in _SUPPORTED_KEYS:
            raise KeyboardGestureError(
                "keyboard impulse uses a key outside Player-1 Control",
                reason_code="unsupported_keyboard_action",
                evidence={"identity": impulse.identity, "key": impulse.key},
            )
        owner = partition.onset_owner(impulse.timestamp_ns)
        if owner is not None:
            tap_counts[owner][impulse.key] = tap_counts[owner].get(impulse.key, 0) + 1

    projections: list[dict[str, Any]] = []
    for window_index in range(len(starts)):
        taps = tap_counts[window_index]
        holds = hold_counts[window_index]
        repeated_taps = sorted(key for key, count in taps.items() if count > 1)
        repeated_holds = sorted(key for key, count in holds.items() if count > 1)
        overlap = sorted(taps.keys() & holds.keys())
        if repeated_taps or repeated_holds or overlap:
            raise KeyboardGestureError(
                "keyboard gestures exceed the Player-1 Control per-frame grammar",
                reason_code="keyboard_gesture_frame_conflict",
                evidence={
                    "window_index": window_index,
                    "repeated_tap_keys": repeated_taps,
                    "repeated_hold_keys": repeated_holds,
                    "tap_hold_overlap": overlap,
                },
            )
        projections.append(
            {
                "key_tap": [key for key in STANDARD_KEYBOARD_KEYS if key in taps],
                "key_hold": [key for key in STANDARD_KEYBOARD_KEYS if key in holds],
            }
        )
    return projections


__all__ = [
    "KeyboardEdge",
    "KeyboardGestureError",
    "KeyboardImpulse",
    "KeyboardKey",
    "KeyboardState",
    "KeyboardTimeline",
    "project_keyboard_timeline",
]
