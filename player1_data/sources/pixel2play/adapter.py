"""Pixel2Play protobuf adapter."""

from __future__ import annotations

import bisect
import logging
import math
from pathlib import Path
from typing import Any

from google.protobuf.json_format import MessageToDict

from player1_data.files import _is_nonempty_file
from player1_data.sources._vendor.p2p_proto.video_annotation_pb2 import VideoAnnotation
from player1_data.sources.common import (
    ACTION_DURATION_MS,
    FrameResizeSpec,
    MaterializedFrame,
    SampleAnchor,
    SamplingConfig,
    SourceQualificationError,
    SourceSession,
    canonical_key_name,
    extract_video_frame,
    iter_sample_times,
    probe_immutable_source_video,
    probe_immutable_source_video_frame_times_ms,
)
from player1_data.standardize.keyboard import (
    KeyboardGestureError,
    KeyboardKey,
    KeyboardState,
    KeyboardTimeline,
)
from player1_data.standardize.mouse import (
    ExactMouseButtonTimeline,
    MouseButtonEdge,
    MouseButtonState,
    QuantizedMouseButtonTimeline,
)
from player1_data.standardize.temporal import (
    ANCHOR_INTERVAL_ONSET_OWNER,
    SourceActionInterval,
)

DATASET_ID = "elefantai/p2p-full-data"
SOURCE_URL = "https://huggingface.co/datasets/elefantai/p2p-full-data"

# Open P2P records the capture library's zero-based mouse button ids.
_BUTTON_NAMES = {"0": "left", "1": "right", "2": "middle", "3": "back", "4": "forward"}
_GAMEPAD_EVENT_TYPES = {
    "game_pad_button_event",
    "game_pad_axis_event",
    "game_pad_trigger_event",
}
_FRAME_OUTPUT_SUBDIR = "p2p-absolute-pts-v1"
_KEYBOARD_LOOKAROUND_NS = 2_000_000_000
_MOUSE_BUTTON_LOOKAROUND_NS = 2_000_000_000
_GESTURE_MAX_SAMPLE_GAP_NS = 75_000_000
_EDGE_ONLY_MODIFIER_KEYS = frozenset({"shift", "control", "alt", "meta"})
LOGGER = logging.getLogger(__name__)


def _button_name(value: str) -> str:
    return _BUTTON_NAMES.get(value, value.lower())


def _game_name(environment: str, subtype: str) -> str:
    environment = environment.strip()
    subtype = subtype.strip()
    base = environment.replace("-", " ").title() if environment else "Unknown"
    detail = subtype.replace("-", " ").title()
    return f"{base}: {detail}" if detail else base


def _has_active_gamepad_state(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_active_gamepad_state(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_active_gamepad_state(item) for item in value)
    if isinstance(value, bool):
        return value
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) != 0.0


class Pixel2PlayAdapter:
    action_provenance = "recorded_key_state"
    source_video_seek_timestamp = True
    source_native_onset_owner_policy = ANCHOR_INTERVAL_ONSET_OWNER

    def __init__(self, recording_root: Path, *, source_revision: str = "local") -> None:
        recording_root = recording_root.expanduser().resolve()
        self.annotation_path = recording_root / "annotation.proto"
        self.video_path = recording_root / "video.mp4"
        if not self.annotation_path.is_file() or not self.video_path.is_file():
            raise FileNotFoundError(
                f"Pixel2Play recording must contain annotation.proto and video.mp4: {recording_root}"
            )
        self.annotation = VideoAnnotation()
        self.annotation.ParseFromString(self.annotation_path.read_bytes())
        self.fps = float(self.annotation.metadata.frames_per_second)
        if self.fps <= 0 or not self.annotation.frame_annotations:
            raise ValueError(f"Pixel2Play recording has no timed frame annotations: {recording_root}")
        self.frame_duration_ms = 1_000.0 / self.fps
        recorded_frame_times_ms = [frame.frame_time / 1_000_000 for frame in self.annotation.frame_annotations]
        has_recorded_frame_times = not all(frame_time_ms == 0 for frame_time_ms in recorded_frame_times_ms)
        if has_recorded_frame_times and (
            any(not math.isfinite(frame_time_ms) or frame_time_ms < 0 for frame_time_ms in recorded_frame_times_ms)
            or any(
                current <= previous
                for previous, current in zip(
                    recorded_frame_times_ms,
                    recorded_frame_times_ms[1:],
                )
            )
        ):
            raise ValueError(
                "Pixel2Play recorded frame times must be all zero or finite, "
                f"nonnegative, and strictly increasing: {recording_root}"
            )
        self.recorded_frame_times_ms = recorded_frame_times_ms if has_recorded_frame_times else None
        self.frame_times_ms = (
            recorded_frame_times_ms
            if has_recorded_frame_times
            else [index * self.frame_duration_ms for index in range(len(self.annotation.frame_annotations))]
        )
        self.video_frame_times_ms = list(probe_immutable_source_video_frame_times_ms(self.video_path))
        if len(self.video_frame_times_ms) != len(self.annotation.frame_annotations):
            raise ValueError(
                "Pixel2Play annotation/video frame counts differ: "
                f"{len(self.annotation.frame_annotations)} annotation frames "
                f"versus {len(self.video_frame_times_ms)} video frames in "
                f"{recording_root}"
            )
        effective_actions = [self._effective_action(index) for index in range(len(self.annotation.frame_annotations))]
        both_known_count = sum(1 for _, _, both_known in effective_actions if both_known)
        if both_known_count:
            LOGGER.warning(
                "Pixel2Play recording %s has %d frames with both actions known; system_action takes precedence",
                recording_root,
                both_known_count,
            )
        self.has_input_timeline = has_recorded_frame_times and any(
            not event.simulated and self._effective_source_at_timestamp_ns(int(event.time))[1] == "user_action"
            for frame in self.annotation.frame_annotations
            for event in frame.input_events
        )
        self.has_mouse_button_input_timeline = has_recorded_frame_times and any(
            not event.simulated
            and event.WhichOneof("event") == "mouse_event"
            and self._effective_source_at_timestamp_ns(int(event.time))[1] == "user_action"
            for frame in self.annotation.frame_annotations
            for event in frame.input_events
        )
        self.duration_ms = self.frame_times_ms[-1] + self.frame_duration_ms
        actions = [action for action, _, _ in effective_actions]
        self.has_gamepad = any(action.HasField("game_pad") for action in actions) or any(
            not event.simulated
            and event.WhichOneof("event") in _GAMEPAD_EVENT_TYPES
            and self._effective_source_at_timestamp_ns(int(event.time))[1] == "user_action"
            for frame in self.annotation.frame_annotations
            for event in frame.input_events
        )
        window = self.annotation.metadata.capture_device_specs.window_specs
        if window.width > 0 and window.height > 0:
            self.observation_size = (window.width, window.height)
            self.observation_geometry_source = "capture_device_specs"
        else:
            video_stream = probe_immutable_source_video(self.video_path)["stream"]
            self.observation_size = (int(video_stream["width"]), int(video_stream["height"]))
            self.observation_geometry_source = "ffprobe_fallback"
        self.session = SourceSession(
            dataset_id=DATASET_ID,
            source_revision=source_revision,
            session_id=self.annotation.metadata.id or recording_root.name,
            game=_game_name(
                self.annotation.metadata.env.env,
                self.annotation.metadata.env.env_subtype,
            ),
            source_files=(self.annotation_path, self.video_path),
            source_metadata={},
        )

    def iter_anchors(self, config: SamplingConfig):
        end = self.duration_ms - 2 * ACTION_DURATION_MS
        previous_index: int | None = None
        previous_time_ms: float | None = None
        sample_times = iter_sample_times(
            start_time_ms=config.start_time_ms,
            end_time_ms=end,
            max_samples=config.max_samples,
        )
        for anchor_index, time_ms in enumerate(sample_times):
            insertion = bisect.bisect_left(self.frame_times_ms, time_ms)
            candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(self.frame_times_ms)]
            index = min(candidates, key=lambda candidate: abs(self.frame_times_ms[candidate] - time_ms))
            if index == previous_index:
                raise SourceQualificationError(
                    "Pixel2Play consecutive decision anchors map to the same source frame",
                    reason_code="source_frame_identity_invalid",
                    evidence={
                        "issue": "repeated_source_frame_for_decision_cadence",
                        "anchor_index": anchor_index,
                        "previous_target_time_ms": round(float(previous_time_ms), 6),
                        "target_time_ms": round(float(time_ms), 6),
                        "source_index": index,
                        "source_frame_time_ms": round(float(self.frame_times_ms[index]), 6),
                    },
                )
            metadata: dict[str, Any] = {
                "action_clock_time_ms": round(
                    float(self.frame_times_ms[index]),
                    6,
                ),
            }
            if self.recorded_frame_times_ms is not None:
                metadata.update(
                    {
                        "capture_clock_time_ms": round(
                            float(self.recorded_frame_times_ms[index]),
                            6,
                        ),
                    }
                )
            previous_index = index
            previous_time_ms = time_ms
            yield SampleAnchor(
                video_time_ms=self.video_frame_times_ms[index],
                source_index=index,
                metadata=metadata,
            )

    def _frame_index(self, anchor: SampleAnchor, relative_time_ms: float) -> int | None:
        if anchor.source_index is not None:
            if not 0 <= anchor.source_index < len(self.frame_times_ms):
                raise ValueError(
                    f"Pixel2Play anchor source index is outside the verified frame mapping: {anchor.source_index}"
                )
            anchor_time_ms = self.frame_times_ms[anchor.source_index]
        else:
            metadata = anchor.metadata or {}
            action_clock_time_ms = metadata.get("action_clock_time_ms")
            capture_clock_time_ms = metadata.get("capture_clock_time_ms")
            if isinstance(action_clock_time_ms, int | float):
                anchor_time_ms = float(action_clock_time_ms)
            elif isinstance(capture_clock_time_ms, int | float):
                anchor_time_ms = float(capture_clock_time_ms)
            else:
                insertion = bisect.bisect_left(
                    self.video_frame_times_ms,
                    anchor.video_time_ms,
                )
                candidates = [
                    index for index in (insertion - 1, insertion) if 0 <= index < len(self.video_frame_times_ms)
                ]
                if not candidates:
                    return None
                anchor_index = min(
                    candidates,
                    key=lambda index: abs(self.video_frame_times_ms[index] - anchor.video_time_ms),
                )
                anchor_time_ms = self.frame_times_ms[anchor_index]
        target_time_ms = anchor_time_ms + relative_time_ms
        insertion = bisect.bisect_left(self.frame_times_ms, target_time_ms)
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(self.frame_times_ms)]
        if not candidates:
            return None
        return min(candidates, key=lambda index: abs(self.frame_times_ms[index] - target_time_ms))

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
                seek_timestamp=True,
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
        video_time_ms = self.video_frame_times_ms[index]
        path = output_root / "frames" / resize.cache_directory / _FRAME_OUTPUT_SUBDIR / f"frame-{index:08d}.jpg"
        return MaterializedFrame(path=path, video_time_ms=video_time_ms)

    def _effective_action(self, index: int) -> tuple[Any, str, bool]:
        frame = self.annotation.frame_annotations[index]
        system_known = bool(frame.system_action.is_known)
        user_known = bool(frame.user_action.is_known)
        if system_known:
            return frame.system_action, "system_action", user_known
        return frame.user_action, "user_action", False

    def _require_known_effective_actions(self, start_index: int, observed_end_ns: int) -> None:
        for index in range(start_index, len(self.frame_times_ms)):
            if self._keyboard_timestamp_ns(index) > observed_end_ns:
                break
            action, _, _ = self._effective_action(index)
            if not action.is_known:
                raise ValueError(
                    f"Pixel2Play gesture evidence crosses an unknown effective action at source frame {index}"
                )

    def _effective_source_at_timestamp_ns(self, timestamp_ns: int) -> tuple[int, str]:
        """Resolve input-event precedence from source time, independent of its container frame."""

        index = bisect.bisect_right(self.frame_times_ms, timestamp_ns / 1_000_000) - 1
        index = min(max(index, 0), len(self.frame_times_ms) - 1)
        return index, self._effective_action(index)[1]

    def _action_state(self, index: int) -> tuple[list[str], list[str], Any]:
        action, _, _ = self._effective_action(index)
        keys = sorted({canonical_key_name(key) for key in action.keyboard.keys}) if action.HasField("keyboard") else []
        buttons = (
            sorted({_button_name(button) for button in action.mouse.buttons_down}) if action.HasField("mouse") else []
        )
        return keys, buttons, action

    def _keyboard_timestamp_ns(self, index: int) -> int:
        if self.recorded_frame_times_ms is not None:
            return int(self.annotation.frame_annotations[index].frame_time)
        return round(index * self.frame_duration_ms * 1_000_000)

    def source_native_action_clock_ns(self, anchor: SampleAnchor) -> int:
        source_index = anchor.source_index
        if (
            isinstance(source_index, bool)
            or not isinstance(source_index, int)
            or not 0 <= source_index < len(self.frame_times_ms)
        ):
            raise ValueError("Pixel2Play action clock requires a bound source frame index")
        return self._keyboard_timestamp_ns(source_index)

    def _keyboard_state(self, index: int, *, source_order: int) -> KeyboardState:
        action, _, _ = self._effective_action(index)
        keys_by_identity: dict[str, KeyboardKey] = {}
        if action.HasField("keyboard"):
            for raw_key in action.keyboard.keys:
                source_key = str(raw_key).strip()
                identity = source_key.casefold()
                keys_by_identity[identity] = KeyboardKey(
                    identity=identity,
                    key=canonical_key_name(source_key),
                )
        return KeyboardState(
            timestamp_ns=self._keyboard_timestamp_ns(index),
            source_order=source_order,
            keys=tuple(sorted(keys_by_identity.values())),
            transition_exact=True,
        )

    def _keyboard_timeline_bounds(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> tuple[tuple[int, ...], int, int]:
        if not math.isclose(horizon_ms, 200.0, abs_tol=1e-6):
            raise ValueError("Pixel2Play keyboard timeline requires a 200 ms action horizon")
        if len(anchors) != 50:
            raise ValueError("Pixel2Play keyboard timeline requires exactly 50 decision anchors")
        source_indices = [anchor.source_index for anchor in anchors]
        if any(index is None or not 0 <= index < len(self.frame_times_ms) for index in source_indices):
            raise ValueError("Pixel2Play keyboard timeline anchors require valid source indices")
        window_starts_ns = tuple(self._keyboard_timestamp_ns(int(index)) for index in source_indices)
        coverage_end_ns = window_starts_ns[-1] + round(horizon_ms * 1_000_000)
        recording_end_ns = round(self.duration_ms * 1_000_000)
        if recording_end_ns < coverage_end_ns:
            raise ValueError("Pixel2Play keyboard evidence does not cover the decision sequence")
        observed_end_ns = min(recording_end_ns, coverage_end_ns + _KEYBOARD_LOOKAROUND_NS)
        return window_starts_ns, coverage_end_ns, observed_end_ns

    def source_native_keyboard_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> KeyboardTimeline:
        """Return one source-authoritative keyboard timeline for 50 decision windows."""

        window_starts_ns, _, observed_end_ns = self._keyboard_timeline_bounds(anchors, horizon_ms)
        lookbehind_start_ns = window_starts_ns[0] - _KEYBOARD_LOOKAROUND_NS
        frame_times_ns = [self._keyboard_timestamp_ns(index) for index in range(len(self.frame_times_ms))]
        seed_index = max(0, bisect.bisect_right(frame_times_ns, lookbehind_start_ns) - 1)
        self._require_known_effective_actions(seed_index, observed_end_ns)
        seed = self._keyboard_state(seed_index, source_order=0)

        if not self.has_input_timeline:
            checkpoints = tuple(
                self._keyboard_state(index, source_order=index + 1)
                for index in range(seed_index + 1, len(self.frame_times_ms))
                if frame_times_ns[index] <= observed_end_ns
            )
            return KeyboardTimeline(
                authority="pixel2play_keyboard_state_snapshots_20hz",
                evidence_kind="state_snapshots",
                window_starts_ns=window_starts_ns,
                seed=seed,
                checkpoints=checkpoints,
                edges=(),
                observed_end_ns=observed_end_ns,
                maximum_sample_gap_ns=_GESTURE_MAX_SAMPLE_GAP_NS,
            )

        ordered_events: list[tuple[int, int, int, str, bool, str]] = []
        for container_index, frame in enumerate(self.annotation.frame_annotations):
            for event_index, event in enumerate(frame.input_events):
                if event.simulated or event.WhichOneof("event") != "keyboard_event":
                    continue
                _, effective_source = self._effective_source_at_timestamp_ns(int(event.time))
                ordered_events.append(
                    (
                        int(event.time),
                        container_index,
                        event_index,
                        str(event.keyboard_event.key),
                        bool(event.keyboard_event.pressed),
                        effective_source,
                    )
                )
        ordered_events.sort(key=lambda item: (item[0], item[1], item[2]))
        snapshot_authoritative_keys = {
            key.key
            for index in range(len(self.frame_times_ms))
            for key in self._keyboard_state(index, source_order=0).keys
            if key.key not in _EDGE_ONLY_MODIFIER_KEYS
        }
        exact_active: dict[str, str] = {}
        snapshot_active: set[str] = set()

        def apply_event(
            source_key: str,
            pressed: bool,
            *,
            timestamp_ns: int,
            allow_orphan: bool,
        ) -> None:
            key = canonical_key_name(source_key)
            if key in snapshot_authoritative_keys:
                if pressed:
                    snapshot_active.add(key)
                else:
                    snapshot_active.discard(key)
                return
            identity = source_key.strip().casefold()
            if pressed:
                previous = exact_active.get(identity)
                if previous is not None and previous != key:
                    raise ValueError("Pixel2Play keyboard identity changed canonical key")
                exact_active[identity] = key
            elif identity in exact_active:
                del exact_active[identity]
            elif not allow_orphan:
                raise KeyboardGestureError(
                    "Pixel2Play exact keyboard release has no matching physical press",
                    reason_code="keyboard_gesture_orphan_release",
                    evidence={"identity": identity, "key": key, "timestamp_ns": timestamp_ns},
                )

        for timestamp_ns, _, _, source_key, pressed, _ in ordered_events:
            if timestamp_ns > seed.timestamp_ns:
                break
            apply_event(source_key, pressed, timestamp_ns=timestamp_ns, allow_orphan=True)

        seed_action, seed_source, _ = self._effective_action(seed_index)
        seed_frame_keys = {
            canonical_key_name(source_key)
            for source_key in (seed_action.keyboard.keys if seed_action.HasField("keyboard") else ())
        }
        snapshot_active = seed_frame_keys & snapshot_authoritative_keys
        effective_source = seed_source
        system_keys = seed_frame_keys if effective_source == "system_action" else set()

        def visible_keys() -> set[str]:
            if effective_source == "system_action":
                return set(system_keys)
            return snapshot_active | set(exact_active.values())

        seed = KeyboardState(
            timestamp_ns=seed.timestamp_ns,
            source_order=0,
            keys=tuple(KeyboardKey(identity=key, key=key) for key in sorted(visible_keys())),
            transition_exact=True,
        )
        records: list[tuple[int, int, int, int, str, Any]] = [
            (frame_times_ns[index], 1, index, -1, "frame", index)
            for index in range(seed_index + 1, len(frame_times_ns))
            if frame_times_ns[index] <= observed_end_ns
        ]
        records.extend(
            (
                timestamp_ns,
                0,
                container_index,
                event_index,
                "event",
                (source_key, pressed, event_source),
            )
            for timestamp_ns, container_index, event_index, source_key, pressed, event_source in ordered_events
            if seed.timestamp_ns < timestamp_ns <= observed_end_ns
        )
        records.sort(key=lambda item: item[:4])
        checkpoints: list[KeyboardState] = []
        previous_visible = visible_keys()
        for timestamp_ns, _, _, _, record_type, payload in records:
            if record_type == "frame":
                action, effective_source, _ = self._effective_action(int(payload))
                frame_keys = {
                    canonical_key_name(source_key)
                    for source_key in (action.keyboard.keys if action.HasField("keyboard") else ())
                }
                if effective_source == "system_action":
                    system_keys = frame_keys
                else:
                    snapshot_active = frame_keys & snapshot_authoritative_keys
            else:
                source_key, pressed, event_source = payload
                apply_event(
                    source_key,
                    pressed,
                    timestamp_ns=timestamp_ns,
                    allow_orphan=False,
                )
                if event_source == "system_action":
                    continue
            current_visible = visible_keys()
            if current_visible == previous_visible and record_type != "frame":
                continue
            checkpoints.append(
                KeyboardState(
                    timestamp_ns=timestamp_ns,
                    source_order=len(checkpoints) + 1,
                    keys=tuple(KeyboardKey(identity=key, key=key) for key in sorted(current_visible)),
                    transition_exact=True,
                )
            )
            previous_visible = current_visible
        return KeyboardTimeline(
            authority="pixel2play_keyboard_reconciled_state_events",
            evidence_kind="state_snapshots",
            window_starts_ns=window_starts_ns,
            seed=seed,
            checkpoints=tuple(checkpoints),
            edges=(),
            observed_end_ns=observed_end_ns,
            maximum_sample_gap_ns=_GESTURE_MAX_SAMPLE_GAP_NS,
        )

    def _mouse_button_timestamp_ns(self, index: int) -> int:
        return self._keyboard_timestamp_ns(index)

    @staticmethod
    def _mouse_buttons(action: Any) -> frozenset[str]:
        if not action.HasField("mouse"):
            return frozenset()
        return frozenset(_button_name(str(button)) for button in action.mouse.buttons_down)

    def _effective_mouse_buttons(self, index: int) -> frozenset[str]:
        action, _, _ = self._effective_action(index)
        return self._mouse_buttons(action)

    def _mouse_button_timeline_bounds(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> tuple[tuple[int, ...], int]:
        if not math.isclose(horizon_ms, 200.0, abs_tol=1e-6):
            raise ValueError("Pixel2Play mouse-button timeline requires a 200 ms action horizon")
        if len(anchors) != 50:
            raise ValueError("Pixel2Play mouse-button timeline requires exactly 50 decision anchors")
        source_indices = [anchor.source_index for anchor in anchors]
        if any(index is None or not 0 <= index < len(self.frame_times_ms) for index in source_indices):
            raise ValueError("Pixel2Play mouse-button timeline anchors require valid source indices")
        window_starts_ns = tuple(self._mouse_button_timestamp_ns(int(index)) for index in source_indices)
        coverage_end_ns = window_starts_ns[-1] + round(horizon_ms * 1_000_000)
        recording_end_ns = round(self.duration_ms * 1_000_000)
        if recording_end_ns < coverage_end_ns:
            raise ValueError("Pixel2Play mouse-button evidence does not cover the decision sequence")
        return (
            window_starts_ns,
            min(recording_end_ns, coverage_end_ns + _MOUSE_BUTTON_LOOKAROUND_NS),
        )

    def source_native_mouse_button_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> ExactMouseButtonTimeline | QuantizedMouseButtonTimeline:
        """Return one source-authoritative mouse-button timeline for 50 decision windows."""

        window_starts_ns, observed_end_ns = self._mouse_button_timeline_bounds(anchors, horizon_ms)
        lookbehind_start_ns = window_starts_ns[0] - _MOUSE_BUTTON_LOOKAROUND_NS
        frame_times_ns = tuple(self._mouse_button_timestamp_ns(index) for index in range(len(self.frame_times_ms)))
        seed_index = max(0, bisect.bisect_right(frame_times_ns, lookbehind_start_ns) - 1)
        seed_timestamp_ns = frame_times_ns[seed_index]
        self._require_known_effective_actions(seed_index, observed_end_ns)

        if not self.has_mouse_button_input_timeline:
            seed = MouseButtonState(
                timestamp_ns=seed_timestamp_ns,
                source_order=0,
                buttons=self._effective_mouse_buttons(seed_index),
            )
            checkpoints = tuple(
                MouseButtonState(
                    timestamp_ns=frame_times_ns[index],
                    source_order=source_order,
                    buttons=self._effective_mouse_buttons(index),
                )
                for source_order, index in enumerate(
                    (
                        index
                        for index in range(seed_index + 1, len(frame_times_ns))
                        if frame_times_ns[index] <= observed_end_ns
                    ),
                    start=1,
                )
            )
            return QuantizedMouseButtonTimeline(
                authority="pixel2play_mouse_button_state_snapshots_20hz",
                window_starts_ns=window_starts_ns,
                seed=seed,
                checkpoints=checkpoints,
                observed_end_ns=observed_end_ns,
                maximum_sample_gap_ns=_GESTURE_MAX_SAMPLE_GAP_NS,
            )

        ordered_events: list[tuple[int, int, int, str, bool, str]] = []
        for container_index, frame in enumerate(self.annotation.frame_annotations):
            for event_index, event in enumerate(frame.input_events):
                if event.simulated or event.WhichOneof("event") != "mouse_event":
                    continue
                _, effective_source = self._effective_source_at_timestamp_ns(int(event.time))
                ordered_events.append(
                    (
                        int(event.time),
                        container_index,
                        event_index,
                        _button_name(str(event.mouse_event.button)),
                        bool(event.mouse_event.pressed),
                        effective_source,
                    )
                )
        ordered_events.sort(key=lambda item: item[:3])

        seed = MouseButtonState(
            timestamp_ns=seed_timestamp_ns,
            source_order=0,
            buttons=self._effective_mouse_buttons(seed_index),
        )

        frames_by_timestamp: dict[int, list[int]] = {}
        for index in range(seed_index + 1, len(frame_times_ns)):
            timestamp_ns = frame_times_ns[index]
            if timestamp_ns > observed_end_ns:
                break
            frames_by_timestamp.setdefault(timestamp_ns, []).append(index)
        events_by_timestamp: dict[int, list[tuple[int, int, str, bool, str]]] = {}
        for timestamp_ns, container_index, event_index, button, pressed, effective_source in ordered_events:
            if seed_timestamp_ns < timestamp_ns <= observed_end_ns:
                events_by_timestamp.setdefault(timestamp_ns, []).append(
                    (container_index, event_index, button, pressed, effective_source)
                )

        checkpoints: list[MouseButtonState] = []
        edges: list[MouseButtonEdge] = []
        source_order = 0

        for timestamp_ns in sorted(frames_by_timestamp.keys() | events_by_timestamp.keys()):
            frame_indices = frames_by_timestamp.get(timestamp_ns, ())
            for _, _, button, pressed, effective_source in events_by_timestamp.get(timestamp_ns, ()):
                if effective_source == "system_action":
                    continue
                source_order += 1
                edges.append(
                    MouseButtonEdge(
                        timestamp_ns=timestamp_ns,
                        source_order=source_order,
                        button=button,
                        pressed=pressed,
                    )
                )

            for frame_index in frame_indices:
                source_order += 1
                checkpoints.append(
                    MouseButtonState(
                        timestamp_ns=timestamp_ns,
                        source_order=source_order,
                        buttons=self._effective_mouse_buttons(frame_index),
                    )
                )

        return ExactMouseButtonTimeline(
            authority="pixel2play_mouse_exact_events_effective_checkpoints",
            window_starts_ns=window_starts_ns,
            seed=seed,
            checkpoints=tuple(checkpoints),
            edges=tuple(edges),
            observed_end_ns=observed_end_ns,
        )

    @staticmethod
    def _pointer_fields(action: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not action.HasField("mouse"):
            return None, None
        mouse = action.mouse
        motion = None
        # Open P2P's released training path consumes mouse_delta_px.  The
        # protobuf fields are independent (not a oneof), so recordings may
        # carry both values; the documented pixel field must win.
        if mouse.HasField("mouse_delta_px"):
            motion = {
                "dx": mouse.mouse_delta_px.x,
                "dy": mouse.mouse_delta_px.y,
                "space": "screen_pixel_delta",
            }
        scroll = None
        if mouse.HasField("scroll_delta_px") and (mouse.scroll_delta_px.x or mouse.scroll_delta_px.y):
            scroll = {
                "dx": mouse.scroll_delta_px.x,
                "dy": mouse.scroll_delta_px.y,
                "space": "scroll_pixel_delta",
            }
        return motion, scroll

    def pointer_samples(self, anchor: SampleAnchor, interval: SourceActionInterval) -> list[dict]:
        clock = self.source_native_action_clock_ns(anchor)
        if interval.anchor_ns != clock or interval.start_ns != clock:
            raise ValueError("Pixel2Play source interval differs from its anchor clock")
        first = anchor.source_index
        start, end = interval.start_ns / 1_000_000, interval.end_ns / 1_000_000
        last = min(bisect.bisect_right(self.frame_times_ms, end), len(self.frame_times_ms) - 1)
        self._require_known_effective_actions(first, interval.end_ns - 1)
        events = []
        if self.has_input_timeline:
            # Include the previous container: a recap edge may be stored one frame late.
            for index in range(max(0, first - 1), last + 1):
                for event in self.annotation.frame_annotations[index].input_events:
                    _, effective = self._effective_source_at_timestamp_ns(int(event.time))
                    if (
                        effective == "system_action"
                        or event.simulated
                        or not interval.start_ns <= event.time < interval.end_ns
                    ):
                        continue
                    kind = event.WhichOneof("event")
                    if kind and kind.startswith("game_pad_"):
                        raise ValueError("unsupported_gamepad_action")
                    events.append(event)
        boundaries = {start, end}
        boundaries.update(t for t in self.frame_times_ms[first : last + 1] if start <= t < end)
        boundaries.update(
            event.time / 1_000_000 for event in events if event.WhichOneof("event") in {"keyboard_event", "mouse_event"}
        )
        points = sorted(boundaries)
        samples = []
        for left, right in zip(points, points[1:]):
            index = bisect.bisect_left(self.frame_times_ms, left)
            sample = {}
            if index < len(self.frame_times_ms) and self.frame_times_ms[index] == left:
                _, _, action = self._action_state(index)
                if action.HasField("game_pad") and _has_active_gamepad_state(
                    MessageToDict(action.game_pad, preserving_proto_field_name=True)
                ):
                    raise ValueError("unsupported_gamepad_action")
                motion, scroll = self._pointer_fields(action)
                if motion is not None:
                    sample["mouse_delta"] = motion
                # Absolute cursor observations are telemetry, never movement actions.
                if not self.has_input_timeline and scroll is not None:
                    sample["scroll"] = scroll
            if self.has_input_timeline:
                wheels = [
                    event.wheel_event
                    for event in events
                    if event.WhichOneof("event") == "wheel_event" and left <= event.time / 1_000_000 < right
                ]
                dx, dy = sum(e.x for e in wheels), sum(e.y for e in wheels)
                if dx or dy:
                    sample["scroll"] = {"dx": dx, "dy": dy, "space": "scroll_pixel_delta"}
            samples.append(sample)
        return samples

    def observation_geometry(self, anchor: SampleAnchor) -> dict[str, Any]:
        return {
            "width_px": self.observation_size[0],
            "height_px": self.observation_size[1],
            "source": self.observation_geometry_source,
        }
