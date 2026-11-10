"""Project source-authoritative mouse gestures onto fixed decision windows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from player1.agents.actions.devices import STANDARD_MOUSE_BUTTONS
from player1_data.standardize.temporal import (
    ANCHOR_INTERVAL_ONSET_OWNER,
    OnsetOwnerPolicy,
    SourceActionPartition,
)

_CLICK_MAX_MS = 300.0
_CORROBORATION_TOLERANCE_MS = 10.0
_SUPPORTED_BUTTONS = frozenset(STANDARD_MOUSE_BUTTONS)


class MouseGestureError(ValueError):
    """The raw button timeline cannot be projected without inventing an action."""

    def __init__(self, message: str, *, reason_code: str, evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.evidence = dict(evidence or {})


@dataclass(frozen=True)
class MouseButtonState:
    timestamp_ns: int
    source_order: int
    buttons: frozenset[str]
    transition_exact: bool = False


@dataclass(frozen=True)
class MouseButtonEdge:
    timestamp_ns: int
    source_order: int
    button: str
    pressed: bool
    evidence_kind: Literal["exact", "inferred_down"] = "exact"


@dataclass(frozen=True)
class ExactMouseButtonTimeline:
    authority: str
    window_starts_ns: tuple[int, ...]
    seed: MouseButtonState
    checkpoints: tuple[MouseButtonState, ...]
    edges: tuple[MouseButtonEdge, ...]
    observed_end_ns: int
    corroborating_edges: tuple[MouseButtonEdge, ...] | None = None
    onset_owner_policy: OnsetOwnerPolicy = ANCHOR_INTERVAL_ONSET_OWNER


@dataclass(frozen=True)
class QuantizedMouseButtonTimeline:
    """A sampled held-button state timeline without exact physical edge times."""

    authority: str
    window_starts_ns: tuple[int, ...]
    seed: MouseButtonState
    checkpoints: tuple[MouseButtonState, ...]
    observed_end_ns: int
    onset_owner_policy: OnsetOwnerPolicy = ANCHOR_INTERVAL_ONSET_OWNER
    maximum_sample_gap_ns: int | None = None


@dataclass(frozen=True)
class _Gesture:
    button: str
    down_ns: int | None
    up_ns: int | None
    observed_held_since_ns: int
    observed_edges: tuple[MouseButtonEdge, ...]
    down_earliest_ns: int | None = None
    up_earliest_ns: int | None = None


def _validate_timeline_header(timeline, partition: SourceActionPartition) -> None:
    if not isinstance(timeline.authority, str) or not timeline.authority:
        raise MouseGestureError(
            "mouse gesture authority must be non-empty text",
            reason_code="mouse_gesture_evidence_invalid",
        )
    if (
        timeline.window_starts_ns != partition.window_starts_ns
        or timeline.onset_owner_policy != partition.onset_owner_policy
        or partition.target_duration_ns != 200_000_000
    ):
        raise MouseGestureError(
            "mouse timeline differs from its recording partition", reason_code="mouse_gesture_evidence_invalid"
        )
    starts = partition.window_starts_ns
    if (
        isinstance(timeline.seed.timestamp_ns, bool)
        or not isinstance(timeline.seed.timestamp_ns, int)
        or isinstance(timeline.seed.source_order, bool)
        or not isinstance(timeline.seed.source_order, int)
        or isinstance(timeline.observed_end_ns, bool)
        or not isinstance(timeline.observed_end_ns, int)
        or not isinstance(timeline.seed.buttons, frozenset)
    ):
        raise MouseGestureError(
            "mouse gesture seed and observed end must use typed integer-nanosecond evidence",
            reason_code="mouse_gesture_evidence_invalid",
        )
    expected_gap_ns = partition.target_duration_ns
    if timeline.seed.timestamp_ns > starts[0] or timeline.observed_end_ns < starts[-1] + expected_gap_ns:
        raise MouseGestureError(
            "mouse gesture evidence does not cover the decision sequence",
            reason_code="mouse_gesture_evidence_invalid",
        )
    if any(not isinstance(state.buttons, frozenset) for state in timeline.checkpoints):
        raise MouseGestureError(
            "mouse gesture checkpoints must contain frozen button sets",
            reason_code="mouse_gesture_evidence_invalid",
        )


def _validate_exact_timeline(timeline: ExactMouseButtonTimeline, partition: SourceActionPartition) -> None:
    _validate_timeline_header(timeline, partition)
    records = (*timeline.checkpoints, *timeline.edges)
    if any(
        isinstance(record.timestamp_ns, bool)
        or not isinstance(record.timestamp_ns, int)
        or isinstance(record.source_order, bool)
        or not isinstance(record.source_order, int)
        or (isinstance(record, MouseButtonEdge) and not isinstance(record.pressed, bool))
        or (isinstance(record, MouseButtonEdge) and record.evidence_kind not in {"exact", "inferred_down"})
        or not timeline.seed.timestamp_ns <= record.timestamp_ns <= timeline.observed_end_ns
        for record in records
    ):
        raise MouseGestureError(
            "mouse gesture records must be typed and fall within their observed integer-nanosecond interval",
            reason_code="mouse_gesture_evidence_invalid",
        )
    tolerance_ns = round(_CORROBORATION_TOLERANCE_MS * 1_000_000)
    if any(
        isinstance(record.timestamp_ns, bool)
        or not isinstance(record.timestamp_ns, int)
        or isinstance(record.source_order, bool)
        or not isinstance(record.source_order, int)
        or not isinstance(record.pressed, bool)
        or record.evidence_kind not in {"exact", "inferred_down"}
        or not timeline.seed.timestamp_ns - tolerance_ns
        <= record.timestamp_ns
        <= timeline.observed_end_ns + tolerance_ns
        for record in timeline.corroborating_edges or ()
    ):
        raise MouseGestureError(
            "corroborating mouse edges must be typed and fall within the observed interval witness margin",
            reason_code="mouse_gesture_evidence_invalid",
        )
    corroborating = timeline.corroborating_edges or ()
    if any(
        right.source_order < left.source_order or right.timestamp_ns < left.timestamp_ns
        for left, right in zip(corroborating, corroborating[1:], strict=False)
    ):
        raise MouseGestureError(
            "corroborating mouse edges do not preserve source order",
            reason_code="mouse_gesture_evidence_invalid",
        )


def _validate_quantized_timeline(timeline: QuantizedMouseButtonTimeline, partition: SourceActionPartition) -> None:
    _validate_timeline_header(timeline, partition)
    if (
        timeline.maximum_sample_gap_ns is None
        or isinstance(timeline.maximum_sample_gap_ns, bool)
        or not isinstance(timeline.maximum_sample_gap_ns, int)
        or timeline.maximum_sample_gap_ns <= 0
    ):
        raise MouseGestureError(
            "quantized mouse evidence requires a positive maximum sample gap",
            reason_code="mouse_gesture_evidence_invalid",
        )
    previous = timeline.seed
    for state in timeline.checkpoints:
        if (
            isinstance(state.timestamp_ns, bool)
            or not isinstance(state.timestamp_ns, int)
            or isinstance(state.source_order, bool)
            or not isinstance(state.source_order, int)
            or not timeline.seed.timestamp_ns <= state.timestamp_ns <= timeline.observed_end_ns
            or state.source_order <= previous.source_order
            or state.timestamp_ns <= previous.timestamp_ns
        ):
            raise MouseGestureError(
                "quantized mouse states must preserve source-time order",
                reason_code="mouse_gesture_evidence_invalid",
            )
        if state.timestamp_ns - previous.timestamp_ns > timeline.maximum_sample_gap_ns:
            raise MouseGestureError(
                "quantized mouse cadence exceeds its source certainty bound",
                reason_code="mouse_gesture_sample_gap_invalid",
                evidence={
                    "gap_ns": state.timestamp_ns - previous.timestamp_ns,
                    "maximum_sample_gap_ns": timeline.maximum_sample_gap_ns,
                },
            )
        previous = state
    if timeline.observed_end_ns - previous.timestamp_ns > timeline.maximum_sample_gap_ns:
        raise MouseGestureError(
            "quantized mouse cadence ends before its source certainty bound",
            reason_code="mouse_gesture_sample_gap_invalid",
            evidence={
                "gap_ns": timeline.observed_end_ns - previous.timestamp_ns,
                "maximum_sample_gap_ns": timeline.maximum_sample_gap_ns,
            },
        )


def _validate_corroboration(
    timeline: ExactMouseButtonTimeline,
    gestures: list[_Gesture],
    *,
    coverage_start_ns: int,
    coverage_end_ns: int,
) -> None:
    corroborating = timeline.corroborating_edges
    if corroborating is None:
        return
    tolerance_ns = round(_CORROBORATION_TOLERANCE_MS * 1_000_000)

    def edges_match(left: MouseButtonEdge, right: MouseButtonEdge) -> bool:
        return (
            left.button == right.button
            and left.pressed == right.pressed
            and abs(left.timestamp_ns - right.timestamp_ns) <= tolerance_ns
        )

    def unmatched(
        required: tuple[MouseButtonEdge, ...],
        candidates: tuple[MouseButtonEdge, ...],
    ) -> MouseButtonEdge | None:
        candidate_start = 0
        for edge in required:
            match = next(
                (index for index in range(candidate_start, len(candidates)) if edges_match(edge, candidates[index])),
                None,
            )
            if match is None:
                return edge
            candidate_start = match + 1
        return None

    paired_witness_edges = tuple(
        MouseButtonEdge(
            timestamp_ns=edge.timestamp_ns,
            source_order=index,
            button=edge.button,
            pressed=edge.pressed,
        )
        for index, edge in enumerate(
            (
                edge
                for edge in corroborating
                if timeline.seed.timestamp_ns <= edge.timestamp_ns <= timeline.observed_end_ns
            ),
            start=1,
        )
    )
    witness_timeline = ExactMouseButtonTimeline(
        authority=f"{timeline.authority}:corroborating",
        window_starts_ns=timeline.window_starts_ns,
        seed=MouseButtonState(
            timestamp_ns=timeline.seed.timestamp_ns,
            source_order=0,
            buttons=timeline.seed.buttons,
        ),
        checkpoints=(),
        edges=paired_witness_edges,
        observed_end_ns=timeline.observed_end_ns,
    )
    try:
        witness_gestures = _pair_gestures(witness_timeline, coverage_end_ns=coverage_end_ns)
    except MouseGestureError as error:
        raise MouseGestureError(
            "corroborating mouse edges cannot be reconciled with the shared state seed",
            reason_code="mouse_gesture_corroboration_mismatch",
            evidence={"witness_reason_code": error.reason_code, **error.evidence},
        ) from error
    relevant_authoritative_indices = {
        index
        for index, gesture in enumerate(gestures)
        if _intersects(gesture, coverage_start_ns=coverage_start_ns, coverage_end_ns=coverage_end_ns)
    }
    relevant_witness_indices = {
        index
        for index, gesture in enumerate(witness_gestures)
        if _intersects(gesture, coverage_start_ns=coverage_start_ns, coverage_end_ns=coverage_end_ns)
    }

    def gestures_match(left: _Gesture, right: _Gesture) -> bool:
        if left.button != right.button:
            return False
        if left.down_ns is None and right.down_ns is None:
            return True
        return any(
            edges_match(left_edge, right_edge)
            for left_edge in left.observed_edges
            for right_edge in right.observed_edges
        )

    changed = True
    while changed:
        changed = False
        for authoritative_index, authoritative in enumerate(gestures):
            for witness_index, witness in enumerate(witness_gestures):
                if (
                    authoritative_index not in relevant_authoritative_indices
                    and witness_index not in relevant_witness_indices
                ) or not gestures_match(authoritative, witness):
                    continue
                if authoritative_index not in relevant_authoritative_indices:
                    relevant_authoritative_indices.add(authoritative_index)
                    changed = True
                if witness_index not in relevant_witness_indices:
                    relevant_witness_indices.add(witness_index)
                    changed = True

    relevant_edge_orders = {
        edge.source_order for index in relevant_authoritative_indices for edge in gestures[index].observed_edges
    }
    relevant_authoritative = tuple(
        edge
        for edge in sorted(timeline.edges, key=lambda item: item.source_order)
        if edge.source_order in relevant_edge_orders
    )
    witness_edge_orders = {
        edge.source_order for index in relevant_witness_indices for edge in witness_gestures[index].observed_edges
    }
    witness_relevant = tuple(edge for edge in paired_witness_edges if edge.source_order in witness_edge_orders)
    for required, candidates, source in (
        (relevant_authoritative, corroborating, "authoritative"),
        (witness_relevant, timeline.edges, "corroborating"),
    ):
        missing = unmatched(required, candidates)
        if missing is not None:
            raise MouseGestureError(
                "authoritative and corroborating mouse edges disagree",
                reason_code="mouse_gesture_corroboration_mismatch",
                evidence={
                    "source": source,
                    "button": missing.button,
                    "pressed": missing.pressed,
                    "timestamp_ns": missing.timestamp_ns,
                },
            )


def _checkpoint_matches_nearby_edge(
    state: MouseButtonState,
    held: set[str],
    edges: tuple[MouseButtonEdge, ...],
    *,
    buttons: set[str] | None = None,
) -> bool:
    tolerance_ns = round(_CORROBORATION_TOLERANCE_MS * 1_000_000)
    expected = set(state.buttons)
    current = set(held)
    if buttons is not None:
        expected.intersection_update(buttons)
        current.intersection_update(buttons)
    for edge in edges:
        if buttons is not None and edge.button not in buttons:
            continue
        if abs(edge.timestamp_ns - state.timestamp_ns) > tolerance_ns:
            continue
        alternative = set(current)
        if edge.source_order < state.source_order:
            if edge.pressed:
                alternative.discard(edge.button)
            else:
                alternative.add(edge.button)
        elif edge.pressed:
            alternative.add(edge.button)
        else:
            alternative.discard(edge.button)
        if expected == alternative:
            return True
    return False


def _pair_gestures(timeline: ExactMouseButtonTimeline, *, coverage_end_ns: int) -> list[_Gesture]:
    held = set(timeline.seed.buttons)
    unsupported = held - _SUPPORTED_BUTTONS
    if unsupported:
        raise MouseGestureError(
            "mouse gesture seed contains unsupported buttons",
            reason_code="unsupported_mouse_button_action",
            evidence={"buttons": sorted(unsupported)},
        )
    open_down: dict[str, MouseButtonEdge | None] = {button: None for button in held}
    observed_since = {button: timeline.seed.timestamp_ns for button in held}
    gestures: list[_Gesture] = []
    records = [(state.source_order, state.timestamp_ns, "state", state) for state in timeline.checkpoints]
    records.extend((edge.source_order, edge.timestamp_ns, "edge", edge) for edge in timeline.edges)
    records.sort(key=lambda record: record[0])
    previous_order = timeline.seed.source_order
    previous_timestamp = timeline.seed.timestamp_ns
    closure_buttons: set[str] | None = None
    for source_order, timestamp_ns, kind, record in records:
        if source_order <= previous_order or timestamp_ns < previous_timestamp:
            raise MouseGestureError(
                "mouse gesture evidence does not preserve source order",
                reason_code="mouse_gesture_evidence_invalid",
            )
        previous_order = source_order
        previous_timestamp = timestamp_ns
        if timestamp_ns >= coverage_end_ns:
            if closure_buttons is None:
                closure_buttons = set(held)
            if not closure_buttons:
                break
            if kind == "state":
                state = record
                assert isinstance(state, MouseButtonState)
                checkpoint_buttons = set(state.buttons) & closure_buttons
                held_buttons = held & closure_buttons
                if checkpoint_buttons != held_buttons and not _checkpoint_matches_nearby_edge(
                    state,
                    held,
                    timeline.edges,
                    buttons=closure_buttons,
                ):
                    raise MouseGestureError(
                        "mouse click edges disagree with a mouse/state checkpoint",
                        reason_code="mouse_gesture_state_mismatch",
                        evidence={
                            "timestamp_ns": state.timestamp_ns,
                            "edge_state": sorted(held_buttons),
                            "checkpoint_state": sorted(checkpoint_buttons),
                        },
                    )
                continue
            edge = record
            assert isinstance(edge, MouseButtonEdge)
            if edge.button not in closure_buttons:
                continue
        elif kind == "state":
            state = record
            assert isinstance(state, MouseButtonState)
            if set(state.buttons) != held and not _checkpoint_matches_nearby_edge(state, held, timeline.edges):
                raise MouseGestureError(
                    "mouse click edges disagree with a mouse/state checkpoint",
                    reason_code="mouse_gesture_state_mismatch",
                    evidence={
                        "timestamp_ns": state.timestamp_ns,
                        "edge_state": sorted(held),
                        "checkpoint_state": sorted(state.buttons),
                    },
                )
            continue
        edge = record
        assert isinstance(edge, MouseButtonEdge)
        if edge.button not in _SUPPORTED_BUTTONS:
            raise MouseGestureError(
                "mouse gesture edge contains an unsupported button",
                reason_code="unsupported_mouse_button_action",
                evidence={"button": edge.button},
            )
        if edge.pressed:
            if edge.button in held:
                raise MouseGestureError(
                    "mouse button was pressed twice without a release",
                    reason_code="mouse_gesture_duplicate_down",
                    evidence={"button": edge.button, "timestamp_ns": edge.timestamp_ns},
                )
            held.add(edge.button)
            open_down[edge.button] = edge
            observed_since[edge.button] = edge.timestamp_ns
            continue
        if edge.button not in held:
            raise MouseGestureError(
                "mouse button was released without an observed press or held seed",
                reason_code="mouse_gesture_orphan_up",
                evidence={"button": edge.button, "timestamp_ns": edge.timestamp_ns},
            )
        down_edge = open_down.pop(edge.button)
        gestures.append(
            _Gesture(
                button=edge.button,
                down_ns=(
                    down_edge.timestamp_ns
                    if down_edge is not None and down_edge.evidence_kind != "inferred_down"
                    else None
                ),
                up_ns=edge.timestamp_ns,
                observed_held_since_ns=observed_since.pop(edge.button),
                observed_edges=((down_edge,) if down_edge is not None else ()) + (edge,),
                down_earliest_ns=(
                    down_edge.timestamp_ns
                    if down_edge is not None and down_edge.evidence_kind != "inferred_down"
                    else None
                ),
                up_earliest_ns=edge.timestamp_ns,
            )
        )
        held.remove(edge.button)
        if closure_buttons is not None:
            closure_buttons.discard(edge.button)
    gestures.extend(
        _Gesture(
            button=button,
            down_ns=(
                open_down[button].timestamp_ns
                if open_down[button] is not None and open_down[button].evidence_kind != "inferred_down"
                else None
            ),
            up_ns=None,
            observed_held_since_ns=observed_since[button],
            observed_edges=((open_down[button],) if open_down[button] is not None else ()),
            down_earliest_ns=(
                open_down[button].timestamp_ns
                if open_down[button] is not None and open_down[button].evidence_kind != "inferred_down"
                else None
            ),
            up_earliest_ns=None,
        )
        for button in sorted(held)
    )
    return gestures


def _is_short(gesture: _Gesture, *, click_max_ns: int, observed_end_ns: int) -> bool:
    if gesture.down_ns is not None and gesture.up_ns is not None:
        return gesture.up_ns - gesture.down_ns <= click_max_ns
    observed_until_ns = gesture.up_ns if gesture.up_ns is not None else observed_end_ns
    if observed_until_ns - gesture.observed_held_since_ns <= click_max_ns:
        raise MouseGestureError(
            "a censored mouse gesture is shorter than the certainty threshold",
            reason_code="mouse_gesture_censored_ambiguous",
            evidence={"button": gesture.button},
        )
    return False


def _intersects(gesture: _Gesture, *, coverage_start_ns: int, coverage_end_ns: int) -> bool:
    if gesture.up_ns is not None and gesture.up_ns <= coverage_start_ns:
        return False
    return gesture.down_ns is None or gesture.down_ns < coverage_end_ns


def _serialize_projections(
    *,
    click_counts: list[dict[str, int]],
    hold_counts: list[dict[str, int]],
) -> list[dict[str, Any]]:
    projections: list[dict[str, Any]] = []
    for index in range(len(click_counts)):
        clicks = click_counts[index]
        holds = hold_counts[index]
        repeated = sorted(button for button, count in clicks.items() if count > 1)
        repeated_holds = sorted(button for button, count in holds.items() if count > 1)
        click_set = set(clicks)
        hold_set = set(holds)
        if repeated or repeated_holds or len(click_set) > 1 or len(hold_set) > 1 or click_set & hold_set:
            raise MouseGestureError(
                "mouse gestures exceed the scalar Player-1 Control button grammar",
                reason_code="mouse_gesture_scalar_conflict",
                evidence={
                    "window_index": index,
                    "repeated_click_buttons": repeated,
                    "repeated_hold_buttons": repeated_holds,
                    "click_buttons": sorted(click_set),
                    "hold_buttons": sorted(hold_set),
                },
            )
        projections.append(
            {
                "mouse_click": min(click_set, default=None),
                "mouse_hold": min(hold_set, default=None),
            }
        )
    return projections


def project_exact_mouse_button_timeline(
    timeline: ExactMouseButtonTimeline, partition: SourceActionPartition
) -> list[dict[str, Any]]:
    """Pair exact source edges once, then assign gestures to unique decision owners."""

    _validate_exact_timeline(timeline, partition)
    starts = partition.window_starts_ns
    click_max_ns = round(_CLICK_MAX_MS * 1_000_000)
    coverage_start_ns = partition.coverage_start_ns
    coverage_end_ns = partition.coverage_end_ns
    gestures = _pair_gestures(timeline, coverage_end_ns=coverage_end_ns)
    _validate_corroboration(
        timeline,
        gestures,
        coverage_start_ns=coverage_start_ns,
        coverage_end_ns=coverage_end_ns,
    )
    click_counts: list[dict[str, int]] = [{} for _ in starts]
    hold_counts: list[dict[str, int]] = [{} for _ in starts]

    for gesture in gestures:
        if not _intersects(gesture, coverage_start_ns=coverage_start_ns, coverage_end_ns=coverage_end_ns):
            continue
        short = _is_short(gesture, click_max_ns=click_max_ns, observed_end_ns=timeline.observed_end_ns)
        if short:
            assert gesture.down_ns is not None
            owner = partition.onset_owner(gesture.down_ns)
            if owner is None:
                if starts[0] <= gesture.down_ns < coverage_end_ns:
                    raise MouseGestureError(
                        "mouse click onset has no decision-window owner",
                        reason_code="mouse_gesture_unowned_click",
                        evidence={"button": gesture.button, "timestamp_ns": gesture.down_ns},
                    )
                continue
            counts = click_counts[owner]
            counts[gesture.button] = counts.get(gesture.button, 0) + 1
            continue
        interval_start_ns = gesture.down_ns if gesture.down_ns is not None else gesture.observed_held_since_ns
        interval_end_ns = gesture.up_ns if gesture.up_ns is not None else timeline.observed_end_ns
        for index in partition.maximum_overlap_full_frame_block(
            interval_start_ns=interval_start_ns,
            interval_end_ns=interval_end_ns,
        ):
            counts = hold_counts[index]
            counts[gesture.button] = counts.get(gesture.button, 0) + 1
    return _serialize_projections(
        click_counts=click_counts,
        hold_counts=hold_counts,
    )


def _pair_quantized_gestures(timeline: QuantizedMouseButtonTimeline) -> list[_Gesture]:
    active = set(timeline.seed.buttons)
    unsupported = active - _SUPPORTED_BUTTONS
    if unsupported:
        raise MouseGestureError(
            "quantized mouse seed contains unsupported buttons",
            reason_code="unsupported_mouse_button_action",
            evidence={"buttons": sorted(unsupported)},
        )
    down_ns: dict[str, int | None] = {button: None for button in active}
    down_earliest_ns: dict[str, int | None] = {button: None for button in active}
    observed_since_ns = {button: timeline.seed.timestamp_ns for button in active}
    gestures: list[_Gesture] = []
    previous = timeline.seed
    for state in timeline.checkpoints:
        next_active = set(state.buttons)
        unsupported = next_active - _SUPPORTED_BUTTONS
        if unsupported:
            raise MouseGestureError(
                "quantized mouse state contains unsupported buttons",
                reason_code="unsupported_mouse_button_action",
                evidence={"buttons": sorted(unsupported)},
            )
        for button in sorted(active - next_active):
            gestures.append(
                _Gesture(
                    button=button,
                    down_ns=down_ns.pop(button),
                    up_ns=state.timestamp_ns,
                    observed_held_since_ns=observed_since_ns.pop(button),
                    observed_edges=(),
                    down_earliest_ns=down_earliest_ns.pop(button),
                    up_earliest_ns=(state.timestamp_ns if state.transition_exact else previous.timestamp_ns),
                )
            )
        for button in sorted(next_active - active):
            down_ns[button] = state.timestamp_ns
            down_earliest_ns[button] = state.timestamp_ns if state.transition_exact else previous.timestamp_ns
            observed_since_ns[button] = state.timestamp_ns
        active = next_active
        previous = state
    gestures.extend(
        _Gesture(
            button=button,
            down_ns=down_ns[button],
            up_ns=None,
            observed_held_since_ns=observed_since_ns[button],
            observed_edges=(),
            down_earliest_ns=down_earliest_ns[button],
            up_earliest_ns=None,
        )
        for button in sorted(active)
    )
    return gestures


def _quantized_gesture_is_click(gesture: _Gesture, *, observed_end_ns: int) -> bool:
    click_max_ns = round(_CLICK_MAX_MS * 1_000_000)
    complete = gesture.down_ns is not None and gesture.up_ns is not None
    if complete:
        assert gesture.down_earliest_ns is not None and gesture.up_earliest_ns is not None
        minimum_duration_ns = max(0, gesture.up_earliest_ns - gesture.down_ns)
        maximum_duration_ns = gesture.up_ns - gesture.down_earliest_ns
        if maximum_duration_ns <= click_max_ns:
            return True
        if minimum_duration_ns > click_max_ns:
            return False
    elif gesture.down_ns is not None:
        minimum_duration_ns = observed_end_ns - gesture.down_ns
        maximum_duration_ns = observed_end_ns - (gesture.down_earliest_ns or gesture.down_ns)
        if minimum_duration_ns > click_max_ns:
            return False
    else:
        end_earliest_ns = gesture.up_earliest_ns if gesture.up_earliest_ns is not None else observed_end_ns
        minimum_duration_ns = end_earliest_ns - gesture.observed_held_since_ns
        maximum_duration_ns = (gesture.up_ns or observed_end_ns) - gesture.observed_held_since_ns
        if minimum_duration_ns > click_max_ns:
            return False
    raise MouseGestureError(
        "quantized mouse duration uncertainty crosses the click/hold boundary",
        reason_code="mouse_gesture_quantized_ambiguous",
        evidence={
            "button": gesture.button,
            "minimum_duration_ns": minimum_duration_ns,
            "maximum_duration_ns": maximum_duration_ns,
            "censored": not complete,
        },
    )


def _quantized_onset_owner(
    gesture: _Gesture,
    partition: SourceActionPartition,
) -> int | None:
    assert gesture.down_ns is not None and gesture.down_earliest_ns is not None
    owners = {partition.onset_owner(timestamp_ns) for timestamp_ns in {gesture.down_earliest_ns, gesture.down_ns}}
    if len(owners) != 1:
        raise MouseGestureError(
            "quantized mouse onset uncertainty crosses a decision boundary",
            reason_code="mouse_gesture_quantized_ambiguous",
            evidence={"button": gesture.button},
        )
    return owners.pop()


def _quantized_hold_block(
    gesture: _Gesture,
    partition: SourceActionPartition,
    observed_end_ns: int,
) -> tuple[int, ...]:
    interval_starts = (
        {gesture.observed_held_since_ns} if gesture.down_ns is None else {gesture.down_earliest_ns, gesture.down_ns}
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
        raise MouseGestureError(
            "quantized mouse uncertainty changes the projected hold frames",
            reason_code="mouse_gesture_quantized_ambiguous",
            evidence={"button": gesture.button},
        )
    return blocks.pop()


def project_quantized_mouse_button_timeline(
    timeline: QuantizedMouseButtonTimeline,
    partition: SourceActionPartition,
) -> list[dict[str, Any]]:
    """Project a 20 Hz held-state timeline using explicit uncertainty bounds."""

    _validate_quantized_timeline(timeline, partition)
    starts = partition.window_starts_ns
    coverage_start_ns = partition.coverage_start_ns
    coverage_end_ns = partition.coverage_end_ns
    click_counts: list[dict[str, int]] = [{} for _ in starts]
    hold_counts: list[dict[str, int]] = [{} for _ in starts]
    for gesture in _pair_quantized_gestures(timeline):
        if not _intersects(gesture, coverage_start_ns=coverage_start_ns, coverage_end_ns=coverage_end_ns):
            continue
        if _quantized_gesture_is_click(gesture, observed_end_ns=timeline.observed_end_ns):
            assert gesture.down_ns is not None
            owner = _quantized_onset_owner(
                gesture,
                partition,
            )
            if owner is not None:
                counts = click_counts[owner]
                counts[gesture.button] = counts.get(gesture.button, 0) + 1
            continue
        for index in _quantized_hold_block(
            gesture,
            partition,
            timeline.observed_end_ns,
        ):
            counts = hold_counts[index]
            counts[gesture.button] = counts.get(gesture.button, 0) + 1
    return _serialize_projections(
        click_counts=click_counts,
        hold_counts=hold_counts,
    )


def project_mouse_button_timeline(
    timeline: ExactMouseButtonTimeline | QuantizedMouseButtonTimeline,
    partition: SourceActionPartition,
) -> list[dict[str, Any]]:
    """Dispatch one source-owned mouse timeline to its matching projector."""

    if isinstance(timeline, ExactMouseButtonTimeline):
        return project_exact_mouse_button_timeline(timeline, partition)
    if isinstance(timeline, QuantizedMouseButtonTimeline):
        return project_quantized_mouse_button_timeline(timeline, partition)
    raise TypeError("source mouse-button timeline type is unsupported")


__all__ = [
    "ExactMouseButtonTimeline",
    "MouseButtonEdge",
    "MouseButtonState",
    "MouseGestureError",
    "QuantizedMouseButtonTimeline",
    "project_exact_mouse_button_timeline",
    "project_mouse_button_timeline",
    "project_quantized_mouse_button_timeline",
]
