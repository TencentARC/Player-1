"""Source-native adapter for Markov Gaming-500-Hours workflows."""

from __future__ import annotations

import bisect
import json
from functools import cached_property
from pathlib import Path
from typing import Any

from player1_data.files import _is_nonempty_file, iter_jsonl
from player1_data.sources.common import (
    ACTION_DURATION_MS,
    FrameResizeSpec,
    MaterializedFrame,
    SampleAnchor,
    SamplingConfig,
    SourceQualificationError,
    SourceSession,
    canonical_key_name,
    canonical_mouse_button_name,
    extract_video_frame,
    iter_sample_times,
)
from player1_data.sources.gaming500.pointer import PointerDecoder, classify_gaming_pointer_timeline
from player1_data.standardize.gui import MODIFIERS, Event, position
from player1_data.standardize.keyboard import (
    KeyboardEdge,
    KeyboardKey,
    KeyboardState,
    KeyboardTimeline,
)
from player1_data.standardize.mouse import (
    ExactMouseButtonTimeline,
    MouseButtonEdge,
    MouseButtonState,
)
from player1_data.standardize.temporal import (
    ANCHOR_INTERVAL_ONSET_OWNER,
    SourceActionInterval,
)

DATASET_ID = "markov-ai/gaming-500-hours"
SOURCE_URL = "https://huggingface.co/datasets/markov-ai/gaming-500-hours"
_POINTER_ACTION_EVENT_TYPES = frozenset({"drag", "mouse_move"})
_KEYBOARD_TIMELINE_AUTHORITY = "gaming_500_hours_raw_input_events_exact_keyboard"
_MOUSE_BUTTON_TIMELINE_AUTHORITY = "gaming_500_hours_raw_input_events_exact_mouse_buttons"
_KEYBOARD_TIMELINE_LOOKAROUND_MS = 2_000.0
_MOUSE_BUTTON_TIMELINE_LOOKAROUND_MS = 2_000.0
_INFERRED_DRAG_CONFIRMATION_MS = 100.0


INPUT_EVENT_TYPES = frozenset({"click", "drag", "key", "mouse_move", "scroll"})
SPECIAL_KEY_NAMES = {
    8: "backspace",
    9: "tab",
    13: "enter",
    16: "shift",
    17: "ctrl",
    18: "alt",
    20: "caps_lock",
    27: "escape",
    32: "space",
    33: "page_up",
    34: "page_down",
    35: "end",
    36: "home",
    37: "arrow_left",
    38: "arrow_up",
    39: "arrow_right",
    40: "arrow_down",
    45: "insert",
    46: "delete",
    91: "left_meta",
    92: "right_meta",
    93: "context_menu",
    160: "left_shift",
    161: "right_shift",
    162: "left_ctrl",
    163: "right_ctrl",
    164: "left_alt",
    165: "right_alt",
}


def key_label(event: dict[str, Any], key_code: int) -> str:
    characters = str(event.get("characters") or "")
    if characters == " ":
        return "space"
    if characters in {"\r", "\n"}:
        return "enter"
    if characters.isprintable() and characters:
        return canonical_key_name(characters)
    return canonical_key_name(SPECIAL_KEY_NAMES.get(key_code, f"key_{key_code}"))


class Gaming500HoursAdapter:
    """Decode ordered Markov input events and pointer geometry."""

    action_provenance = "recorded_key_state"
    source_native_onset_owner_policy = ANCHOR_INTERVAL_ONSET_OWNER

    def gui_events(self):
        """Bind key releases by physical code; release events may omit characters."""
        mode = self._pointer_modes
        blocked = sorted(
            (interval.start_ms, interval.end_ms) for interval in (*mode.locked_intervals, *mode.ambiguous_intervals)
        )
        blocked_index = 0
        events, active_keys = [], set()
        key_labels = {}
        previous_geometry = None
        contexts = {}
        records = sorted(
            [*self.raw_input_events, *self.pointer_context_events],
            key=lambda r: (r["video_t_ms"], r["source_frame"], r["source_event_index"]),
        )
        for record in records:
            time_ms = record["video_t_ms"]
            now = round(time_ms * 1e6)
            raw, kind = record["event"], record["event_type"]
            locator = {"source_frame": record["source_frame"], "source_event_index": record["source_event_index"]}

            def add(event_kind, **data):
                events.append(Event(now, event_kind, data, locator))

            if kind in {"screen_config", "active_app"}:
                token = (raw.get("bundleId") or raw.get("name")) if kind == "active_app" else raw.get("screens")
                if token != contexts.get(kind):
                    add("boundary", reason="active application or screen configuration changed")
                contexts[kind] = token
                continue

            if kind == "key":
                code = raw["keyCode"]
                if raw["isDown"]:
                    key = key_labels.setdefault(code, key_label(raw, code))
                else:
                    key = key_labels.pop(code, key_label(raw, code))
                active_keys = set(key_labels.values())

            while blocked_index < len(blocked) and blocked[blocked_index][1] < time_ms:
                blocked_index += 1
            if (
                record["timing_status"] != "exact"
                or blocked_index < len(blocked)
                and blocked[blocked_index][0] <= time_ms <= blocked[blocked_index][1]
            ):
                add("boundary", reason="pointer-mode or input-time evidence unresolved")
                continue
            if kind == "key":
                if key in MODIFIERS:
                    if not raw.get("isRepeat"):
                        add("modifier", key=key, down=raw["isDown"])
                else:
                    add("modifier_state", keys=sorted(active_keys & MODIFIERS))
                    add("key_down" if raw["isDown"] else "key_up", key=key)
                continue
            add("keyboard_state", keys=sorted(active_keys - MODIFIERS))
            if kind == "scroll":
                if not raw.get("deltaX") and not raw.get("deltaY"):
                    continue
                add("modifier_state", keys=sorted(active_keys & MODIFIERS))
                add("scroll", dx=raw.get("deltaX", 0), dy=raw.get("deltaY", 0), unit="source_scroll_delta")
                continue
            point = self.pointer_point_by_ref.get((record["source_frame"], record["source_event_index"]))
            if not point or point["mapping_status"] != "exact" or not point["in_bounds"]:
                add("boundary", reason="absolute cursor mapping unavailable")
                continue
            geometry = point["screen_geometry"]
            token = tuple(geometry[field] for field in ("index", "origin_x", "origin_y", "width", "height"))
            if previous_geometry is not None and token != previous_geometry:
                add("boundary", reason="screen geometry changed")
            previous_geometry = token
            source = point["source"]
            target = position(
                source["x"] - geometry["origin_x"],
                source["y"] - geometry["origin_y"],
                geometry["width"],
                geometry["height"],
            )
            if kind in {"mouse_move", "drag"}:
                add("move", position=target)
            elif kind == "click" and isinstance(raw.get("isDown"), bool):
                button = canonical_mouse_button_name(raw["button"])
                if button not in {"left", "right", "middle"}:
                    add("boundary", reason="unsupported mouse button")
                else:
                    if raw["isDown"]:
                        add("modifier_state", keys=sorted(active_keys & MODIFIERS))
                    add("press" if raw["isDown"] else "release", button=button, position=target)
            else:
                add("boundary", reason="unresolved GUI mouse gesture")
        return events

    def __init__(self, workflow_root: Path, *, source_revision: str = "local") -> None:
        self.workflow_root = workflow_root.expanduser().resolve()
        self.video_path = self.workflow_root / "clip.mp4"
        self.frame_events_path = self.workflow_root / "frame_events.json"
        self.metadata_path = self.workflow_root / "metadata.json"
        source_files = (self.video_path, self.frame_events_path, self.metadata_path)
        missing = [path.name for path in source_files if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Gaming-500-Hours workflow is missing {missing}: {self.workflow_root}")

        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        frames = list(iter_jsonl(self.frame_events_path))
        if not frames:
            raise ValueError(f"Gaming-500-Hours workflow has no frame events: {self.workflow_root}")
        frame_ids: list[int] = []
        for row_index, raw_frame in enumerate(frames):
            frame_id = raw_frame.get("frame")
            if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0:
                raise SourceQualificationError(
                    f"Gaming-500-Hours source frame identity is invalid at row {row_index}: {frame_id!r}",
                    reason_code="source_frame_identity_invalid",
                    evidence={
                        "row_index": row_index,
                        "frame": frame_id,
                        "issue": "missing_or_non_negative_integer_required",
                    },
                )
            if frame_ids and frame_id <= frame_ids[-1]:
                raise SourceQualificationError(
                    f"Gaming-500-Hours source frame identities must be strictly increasing: {self.workflow_root}",
                    reason_code="source_frame_identity_invalid",
                    evidence={
                        "row_index": row_index,
                        "previous_frame": frame_ids[-1],
                        "frame": frame_id,
                        "issue": "duplicate" if frame_id == frame_ids[-1] else "not_strictly_increasing",
                    },
                )
            frame_ids.append(frame_id)
        self.frame_ids = frame_ids
        self.frame_times_ms = [float(frame.get("video_t_ms", 0.0)) for frame in frames]
        if any(current <= previous for previous, current in zip(self.frame_times_ms, self.frame_times_ms[1:])):
            raise ValueError(f"Gaming-500-Hours frame times must be strictly increasing: {self.workflow_root}")
        self.duration_ms = float(
            metadata.get("total_duration_ms") or metadata.get("duration_ms") or self.frame_times_ms[-1]
        )
        if self.duration_ms <= self.frame_times_ms[-1]:
            frame_duration = (
                self.frame_times_ms[-1] - self.frame_times_ms[-2] if len(self.frame_times_ms) > 1 else 1_000.0 / 30.0
            )
            self.duration_ms = self.frame_times_ms[-1] + frame_duration

        pointer_decoder = PointerDecoder()
        self.frame_context = []
        self.pointer_points: list[dict[str, Any]] = []
        self.pointer_failures: list[dict[str, Any]] = []
        self.pointer_point_by_ref: dict[tuple[int, int], dict[str, Any]] = {}
        self.raw_input_events: list[dict[str, Any]] = []
        self.pointer_context_events: list[dict[str, Any]] = []
        for raw_frame in frames:
            mapping = pointer_decoder.process_frame(raw_frame)
            self.frame_context.append({"screens": mapping["screens"], "active_app": mapping["active_app"]})
            frame_number = int(raw_frame["frame"])
            frame_time = float(raw_frame["video_t_ms"])
            for point in mapping["points"]:
                point["source_frame"] = frame_number
                self.pointer_points.append(point)
                self.pointer_point_by_ref[(frame_number, int(point["event_index"]))] = point
            for failure in mapping["failures"]:
                failure["source_frame"] = frame_number
                self.pointer_failures.append(failure)
            for event_index, event in enumerate(raw_frame.get("events") or []):
                if not isinstance(event, dict):
                    continue
                event_type = str(event.get("type") or "")
                video_t_ms = event.get("video_t_ms")
                has_exact_time = isinstance(video_t_ms, int | float)
                event_time = float(video_t_ms) if has_exact_time else frame_time
                record = {
                    "event": event,
                    "event_type": event_type,
                    "video_t_ms": event_time,
                    "source_frame": frame_number,
                    "source_event_index": event_index,
                    "timing_status": "exact" if has_exact_time else "frame_fallback",
                }
                if event_type in INPUT_EVENT_TYPES:
                    self.raw_input_events.append(record)
                if event_type in {"screen_config", "active_app"}:
                    self.pointer_context_events.append(record)

        screens = [screen for row in self.frame_context for screen in row["screens"]]
        if not screens:
            raise ValueError("Gaming-500-Hours workflow has no valid screen_config geometry")
        default_screen = next((screen for screen in screens if screen["index"] == 0), screens[0])
        self.observation_size = (int(default_screen["width"]), int(default_screen["height"]))

        def event_order(record: dict[str, Any]) -> tuple[float, int, int]:
            return (
                float(record["video_t_ms"]),
                int(record["source_frame"]),
                int(record.get("source_event_index", record.get("event_index", -1))),
            )

        for records in (
            self.pointer_points,
            self.pointer_failures,
            self.raw_input_events,
            self.pointer_context_events,
        ):
            records.sort(key=event_order)
        self.pointer_point_times = [float(record["video_t_ms"]) for record in self.pointer_points]
        self.pointer_failure_times = [float(record["video_t_ms"]) for record in self.pointer_failures]
        self.raw_input_event_times = [float(record["video_t_ms"]) for record in self.raw_input_events]
        self.pointer_context_event_times = [float(record["video_t_ms"]) for record in self.pointer_context_events]
        self.workflow_id = str(metadata.get("workflow_id") or self.workflow_root.name)
        game = str(metadata.get("game") or "unknown")
        self.session = SourceSession(
            dataset_id=DATASET_ID,
            source_revision=source_revision,
            session_id=self.workflow_id,
            game=game,
            source_files=source_files,
            source_metadata={},
        )

    def iter_anchors(self, config: SamplingConfig):
        end = self.duration_ms - 2 * ACTION_DURATION_MS
        for time_ms in iter_sample_times(
            start_time_ms=config.start_time_ms,
            end_time_ms=end,
            max_samples=config.max_samples,
        ):
            index = self._nearest_frame_index(time_ms)
            yield SampleAnchor(
                video_time_ms=self.frame_times_ms[index],
                source_index=index,
            )

    def source_native_keyboard_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> KeyboardTimeline:
        """Return exact ordered key edges from the raw session event ledger."""

        if not anchors:
            raise ValueError("Gaming-500-Hours keyboard timeline requires decision anchors")
        if isinstance(horizon_ms, bool) or not isinstance(horizon_ms, int | float) or horizon_ms <= 0:
            raise ValueError("Gaming-500-Hours keyboard timeline horizon must be positive")

        window_starts_ns = tuple(round(float(anchor.video_time_ms) * 1_000_000) for anchor in anchors)
        coverage_end_ms = float(anchors[-1].video_time_ms) + float(horizon_ms)
        if coverage_end_ms > self.duration_ms + 1e-6:
            raise ValueError("Gaming-500-Hours keyboard timeline exceeds the source duration")

        seed_time_ms = max(0.0, float(anchors[0].video_time_ms) - _KEYBOARD_TIMELINE_LOOKAROUND_MS)
        observed_end_ms = min(self.duration_ms, coverage_end_ms + _KEYBOARD_TIMELINE_LOOKAROUND_MS)
        seed_record_count = bisect.bisect_right(self.raw_input_event_times, seed_time_ms)
        observed_record_count = bisect.bisect_right(self.raw_input_event_times, observed_end_ms)

        def raw_key(record: dict[str, Any]) -> tuple[str, str, bool, bool] | None:
            if record["event_type"] != "key":
                return None
            if record["timing_status"] != "exact":
                raise ValueError("Gaming-500-Hours keyboard gesture evidence requires exact event timestamps")
            event = record["event"]
            key_code = event.get("keyCode")
            is_down = event.get("isDown")
            is_repeat = event.get("isRepeat")
            if (
                not isinstance(key_code, int)
                or key_code < 0
                or not isinstance(is_down, bool)
                or not isinstance(is_repeat, bool)
            ):
                raise ValueError("Gaming-500-Hours keyboard gesture contains an invalid raw key event")
            return str(key_code), key_label(event, key_code), is_down, is_repeat

        active: dict[str, str] = {}
        ambiguous: set[str] = set()
        for record in self.raw_input_events[:seed_record_count]:
            key = raw_key(record)
            if key is None:
                continue
            identity, label, pressed, is_repeat = key
            if pressed:
                if identity not in active:
                    active[identity] = label
                elif not is_repeat:
                    ambiguous.add(identity)
            else:
                active.pop(identity, None)
                ambiguous.discard(identity)
        if ambiguous:
            raise ValueError("Gaming-500-Hours keyboard seed contains an unresolved duplicate press")

        seed_active = dict(active)
        replayed_edges: list[KeyboardEdge] = []
        for record_index, record in enumerate(
            self.raw_input_events[seed_record_count:observed_record_count],
            start=seed_record_count,
        ):
            key = raw_key(record)
            if key is None:
                continue
            identity, label, pressed, is_repeat = key
            if pressed:
                if is_repeat:
                    if identity not in active:
                        raise ValueError("Gaming-500-Hours keyboard repeat has no observed press or held seed")
                    continue
                if identity in active:
                    raise ValueError("Gaming-500-Hours keyboard contains a duplicate physical press")
                active[identity] = label
                replayed_edges.append(
                    KeyboardEdge(
                        timestamp_ns=round(float(record["video_t_ms"]) * 1_000_000),
                        source_order=record_index + 1,
                        identity=identity,
                        key=label,
                        pressed=True,
                    )
                )
            else:
                active_label = active.pop(identity, None)
                if active_label is None:
                    raise ValueError("Gaming-500-Hours keyboard release has no observed press or held seed")
                replayed_edges.append(
                    KeyboardEdge(
                        timestamp_ns=round(float(record["video_t_ms"]) * 1_000_000),
                        source_order=record_index + 1,
                        identity=identity,
                        key=active_label,
                        pressed=False,
                    )
                )
        seed_keys = tuple(KeyboardKey(identity=identity, key=label) for identity, label in sorted(seed_active.items()))
        exact_edges = tuple(edge for edge in replayed_edges if edge.timestamp_ns > round(seed_time_ms * 1_000_000))
        return KeyboardTimeline(
            authority=_KEYBOARD_TIMELINE_AUTHORITY,
            evidence_kind="exact_edges",
            window_starts_ns=window_starts_ns,
            seed=KeyboardState(
                timestamp_ns=round(seed_time_ms * 1_000_000),
                source_order=seed_record_count,
                keys=seed_keys,
            ),
            checkpoints=(),
            edges=exact_edges,
            observed_end_ns=round(observed_end_ms * 1_000_000),
        )

    def source_native_mouse_button_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> ExactMouseButtonTimeline:
        """Return exact physical button edges reconstructed from the raw session ledger."""

        if not anchors:
            raise ValueError("Gaming-500-Hours mouse-button timeline requires decision anchors")
        if isinstance(horizon_ms, bool) or not isinstance(horizon_ms, int | float) or horizon_ms <= 0:
            raise ValueError("Gaming-500-Hours mouse-button timeline horizon must be positive")

        window_starts_ns = tuple(round(float(anchor.video_time_ms) * 1_000_000) for anchor in anchors)
        coverage_end_ms = float(anchors[-1].video_time_ms) + float(horizon_ms)
        if coverage_end_ms > self.duration_ms + 1e-6:
            raise ValueError("Gaming-500-Hours mouse-button timeline exceeds the source duration")

        seed_time_ms = max(0.0, float(anchors[0].video_time_ms) - _MOUSE_BUTTON_TIMELINE_LOOKAROUND_MS)
        observed_end_ms = min(self.duration_ms, coverage_end_ms + _MOUSE_BUTTON_TIMELINE_LOOKAROUND_MS)
        seed_record_count = bisect.bisect_right(self.raw_input_event_times, seed_time_ms)
        observed_record_count = bisect.bisect_right(self.raw_input_event_times, observed_end_ms)

        def raw_button(record: dict[str, Any]) -> tuple[str, str, float, bool | None] | None:
            event_type = record["event_type"]
            if event_type not in {"click", "drag"}:
                return None
            if record["timing_status"] != "exact":
                raise ValueError("Gaming-500-Hours mouse-button gesture evidence requires exact event timestamps")
            event = record["event"]
            raw_button = event.get("button")
            if raw_button is None or isinstance(raw_button, bool):
                raise ValueError("Gaming-500-Hours mouse-button gesture has an invalid raw button")
            button = canonical_mouse_button_name(raw_button)
            if not button:
                raise ValueError("Gaming-500-Hours mouse-button gesture has an empty raw button")
            timestamp_ms = float(record["video_t_ms"])
            if event_type == "drag":
                return event_type, button, timestamp_ms, None
            pressed = event.get("isDown")
            if not isinstance(pressed, bool):
                raise ValueError("Gaming-500-Hours raw click must carry a boolean isDown")
            return event_type, button, timestamp_ms, pressed

        active: dict[str, tuple[bool, float]] = {}
        ambiguous: set[str] = set()
        for record in self.raw_input_events[:seed_record_count]:
            parsed = raw_button(record)
            if parsed is None:
                continue
            event_type, button, timestamp_ms, pressed = parsed
            if event_type == "drag":
                active.setdefault(button, (True, timestamp_ms))
            elif pressed:
                held = active.get(button)
                if held is None or held[0] and timestamp_ms - held[1] <= _INFERRED_DRAG_CONFIRMATION_MS:
                    active[button] = (False, timestamp_ms)
                else:
                    ambiguous.add(button)
            else:
                active.pop(button, None)
                ambiguous.discard(button)
        if ambiguous:
            raise ValueError("Gaming-500-Hours mouse seed contains an unresolved duplicate press")

        seed_buttons = frozenset(active)
        replayed_edges: list[MouseButtonEdge] = []
        for record_index, record in enumerate(
            self.raw_input_events[seed_record_count:observed_record_count],
            start=seed_record_count,
        ):
            parsed = raw_button(record)
            if parsed is None:
                continue
            event_type, button, timestamp_ms, pressed = parsed
            if event_type == "drag":
                if button in active:
                    continue
                active[button] = (True, timestamp_ms)
                replayed_edges.append(
                    MouseButtonEdge(
                        timestamp_ns=round(timestamp_ms * 1_000_000),
                        source_order=record_index + 1,
                        button=button,
                        pressed=True,
                        evidence_kind="inferred_down",
                    )
                )
                continue
            if pressed:
                held = active.get(button)
                if held is None:
                    active[button] = (False, timestamp_ms)
                    replayed_edges.append(
                        MouseButtonEdge(
                            timestamp_ns=round(timestamp_ms * 1_000_000),
                            source_order=record_index + 1,
                            button=button,
                            pressed=True,
                        )
                    )
                    continue
                inferred, inferred_at_ms = held
                if not inferred:
                    raise ValueError("Gaming-500-Hours mouse contains a duplicate physical press")
                if timestamp_ms - inferred_at_ms > _INFERRED_DRAG_CONFIRMATION_MS:
                    raise ValueError("Gaming-500-Hours exact mouse press is too late to confirm an inferred drag")
                active[button] = (False, timestamp_ms)
                continue
            if button not in active:
                raise ValueError("Gaming-500-Hours mouse release has no observed press or held seed")
            active.pop(button)
            replayed_edges.append(
                MouseButtonEdge(
                    timestamp_ns=round(timestamp_ms * 1_000_000),
                    source_order=record_index + 1,
                    button=button,
                    pressed=False,
                )
            )

        edges = tuple(replayed_edges)

        return ExactMouseButtonTimeline(
            authority=_MOUSE_BUTTON_TIMELINE_AUTHORITY,
            window_starts_ns=window_starts_ns,
            seed=MouseButtonState(
                timestamp_ns=round(seed_time_ms * 1_000_000),
                source_order=seed_record_count,
                buttons=seed_buttons,
            ),
            checkpoints=(),
            edges=edges,
            observed_end_ns=round(observed_end_ms * 1_000_000),
        )

    def _nearest_frame_index(self, video_time_ms: float) -> int:
        insertion = bisect.bisect_left(self.frame_times_ms, video_time_ms)
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(self.frame_ids)]
        if not candidates:
            raise ValueError(f"No frame near {video_time_ms}ms")
        return min(candidates, key=lambda index: abs(self.frame_times_ms[index] - video_time_ms))

    def _frame_index(self, anchor: SampleAnchor, relative_time_ms: float) -> int | None:
        target_time_ms = anchor.video_time_ms + relative_time_ms
        if target_time_ms < 0 or target_time_ms >= self.duration_ms:
            return None
        return self._nearest_frame_index(target_time_ms)

    def materialize_frame(
        self,
        anchor: SampleAnchor,
        relative_time_ms: float,
        output_root: Path,
        *,
        resize: FrameResizeSpec,
    ) -> MaterializedFrame | None:
        planned = self._planned_frame(anchor, relative_time_ms, output_root, resize=resize)
        if planned is None:
            return None
        if not _is_nonempty_file(planned.path):
            extract_video_frame(
                self.video_path,
                planned.video_time_ms,
                planned.path,
                resize=resize,
            )
        return planned

    def _planned_frame(
        self,
        anchor: SampleAnchor,
        relative_time_ms: float,
        output_root: Path,
        *,
        resize: FrameResizeSpec,
    ) -> MaterializedFrame | None:
        index = self._frame_index(anchor, relative_time_ms)
        if index is None:
            return None
        video_time_ms = self.frame_times_ms[index]
        frame_number = self.frame_ids[index]
        path = output_root / "frames" / resize.cache_directory / f"frame-{frame_number:08d}.jpg"
        return MaterializedFrame(path=path, video_time_ms=video_time_ms)

    @staticmethod
    def _window_records(
        records: list[dict[str, Any]],
        times: list[float],
        start_ms: float,
        end_ms: float,
    ) -> list[dict[str, Any]]:
        return records[bisect.bisect_left(times, start_ms) : bisect.bisect_left(times, end_ms)]

    def _screen_at(self, frame_index: int) -> dict[str, Any]:
        screens = self.frame_context[frame_index]["screens"]
        if not screens:
            frame = self.frame_ids[frame_index]
            raise SourceQualificationError(
                f"No screen geometry at Markov frame {frame}",
                reason_code="capture_geometry_missing_at_anchor",
                evidence={"frame": frame},
            )
        return next((screen for screen in screens if screen["index"] == 0), screens[0])

    @staticmethod
    def _cursor_from_point(point: dict[str, Any] | None) -> dict[str, Any] | None:
        if point is None:
            return None
        source = point["source"]
        screen = point["screen_geometry"]
        return {
            "x": round(float(source["x"]) - float(screen["origin_x"]), 6),
            "y": round(float(source["y"]) - float(screen["origin_y"]), 6),
            "space": "screen_pixels",
            "screen_index": int(point["screen_index"]),
            "mapping_status": point["mapping_status"],
        }

    @staticmethod
    def source_native_action_clock_ns(anchor: SampleAnchor) -> int:
        return round(float(anchor.video_time_ms) * 1_000_000)

    @cached_property
    def _pointer_modes(self):
        return classify_gaming_pointer_timeline(self.pointer_points)

    def pointer_samples(self, anchor: SampleAnchor, interval: SourceActionInterval) -> list[dict]:
        if interval.anchor_ns != self.source_native_action_clock_ns(anchor):
            raise ValueError("Gaming-500-Hours source interval differs from its anchor clock")
        start, end = interval.start_ns / 1_000_000, interval.end_ns / 1_000_000
        raw = self._window_records(self.raw_input_events, self.raw_input_event_times, start, end)
        points = self._window_records(self.pointer_points, self.pointer_point_times, start, end)
        failures = self._window_records(self.pointer_failures, self.pointer_failure_times, start, end)
        context = self._window_records(self.pointer_context_events, self.pointer_context_event_times, start, end)
        if not isinstance(self.frame_context[anchor.source_index]["active_app"], dict):
            raise ValueError("active_application_unknown")
        if failures:
            raise ValueError("pointer_mapping_unavailable")
        if any(record["timing_status"] != "exact" for record in raw):
            raise ValueError("input_event_timestamp_missing")
        screen = int(self._screen_at(anchor.source_index)["index"])
        if any(point["screen_index"] != screen for point in points):
            raise ValueError("pointer_capture_screen_alignment_unverified")
        boundaries = {start, end}
        boundaries.update(float(r["video_t_ms"]) for r in (*raw, *context))
        boundaries = sorted(boundaries)
        modes = self._pointer_modes
        if modes.ambiguous_intervals:
            raise ValueError("Gaming500 pointer mode is ambiguous; cannot invent camera inputs")
        locked = any(i.start_ms <= anchor.video_time_ms <= i.end_ms for i in modes.locked_intervals)
        samples = []
        for left, right in zip(boundaries, boundaries[1:]):
            sample = {}
            selected = [
                p
                for p in points
                if left <= float(p["video_t_ms"]) < right
                and (
                    p["event_type"] in _POINTER_ACTION_EVENT_TYPES
                    or p["event_type"] == "click"
                    and bool(p.get("isDown"))
                )
            ]
            if selected and not locked:
                sample["cursor"] = self._cursor_from_point(selected[-1])
            wheels = [r["event"] for r in raw if r["event_type"] == "scroll" and left <= float(r["video_t_ms"]) < right]
            if wheels:
                sample["scroll"] = {
                    "dx": round(sum(float(e.get("deltaX") or 0) for e in wheels), 6),
                    "dy": round(sum(float(e.get("deltaY") or 0) for e in wheels), 6),
                    "space": "source_scroll_delta",
                }
            samples.append(sample)
        return samples

    def observation_geometry(self, anchor: SampleAnchor) -> dict[str, Any]:
        assert anchor.source_index is not None
        screen = self._screen_at(anchor.source_index)
        return {
            "width_px": int(screen["width"]),
            "height_px": int(screen["height"]),
            "source": f"screen_config:screen_{screen['index']}",
        }
