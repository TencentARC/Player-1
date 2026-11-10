"""D2E-Original recordings, video alignment and native input evidence."""

from __future__ import annotations

import bisect
import math
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from player1_data.files import _is_nonempty_file
from player1_data.sources.common import (
    ACTION_DURATION_MS,
    MaterializedFrame,
    SampleAnchor,
    SamplingConfig,
    SourceQualificationError,
    SourceSession,
    canonical_mouse_button_name,
    extract_video_frame,
    iter_sample_times,
    probe_immutable_source_video,
)
from player1_data.sources.d2e.index import desktop_mcap_session_index
from player1_data.sources.media_tools import resolve_ffmpeg
from player1_data.standardize.calibration import pixel_scroll_dy
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

ADAPTER_ID = "d2e"
DATASET_ID = "open-world-agents/D2E-Original"
SOURCE_URL = "https://huggingface.co/datasets/open-world-agents/D2E-Original"
_SOURCE_LABEL = "D2E-Original"
D2E_INPUT_PROFILE = "d2e_original_desktop_mcap_input"
_VIRTUAL_KEY_NAMES = {
    8: "backspace",
    9: "tab",
    12: "clear",
    13: "enter",
    16: "shift",
    17: "control",
    18: "alt",
    20: "capslock",
    25: "hanja_kanji",
    27: "escape",
    32: "space",
    33: "pageup",
    34: "pagedown",
    35: "end",
    36: "home",
    37: "arrowleft",
    38: "arrowup",
    39: "arrowright",
    40: "arrowdown",
    45: "insert",
    46: "delete",
    91: "meta",
    96: "numpad0",
    97: "numpad1",
    98: "numpad2",
    99: "numpad3",
    100: "numpad4",
    101: "numpad5",
    102: "numpad6",
    103: "numpad7",
    104: "numpad8",
    105: "numpad9",
    110: "decimal",
    144: "num_lock",
    160: "shift",
    161: "shift",
    162: "control",
    163: "control",
    164: "alt",
    165: "alt",
    174: "volume_down",
    175: "volume_up",
    179: "media_play_pause",
    185: "media_select",
    186: ";",
    187: "=",
    188: ",",
    189: "-",
    190: ".",
    191: "/",
    192: "`",
    219: "[",
    220: "\\",
    221: "]",
    222: "'",
}

_PLAYER1_EXPRESSIBLE_MOUSE_BUTTONS = frozenset({"left", "right", "middle"})
_RAW_MOUSE_BUTTON_FLAGS = (
    (0x0001, "left", True),
    (0x0002, "left", False),
    (0x0004, "right", True),
    (0x0008, "right", False),
    (0x0010, "middle", True),
    (0x0020, "middle", False),
    (0x0040, "back", True),
    (0x0080, "back", False),
    (0x0100, "forward", True),
    (0x0200, "forward", False),
)
_MOUSE_EDGE_WITNESS_TOLERANCE_NS = 10_000_000
_KEYBOARD_EDGE_WITNESS_TOLERANCE_NS = 10_000_000
_MAX_SCREEN_FRAME_ALIGNMENT_ERROR_MS = 50.0
DESKTOP_MCAP_BASE_SELECTED_TOPICS = (
    "screen",
    "keyboard/state",
    "keyboard",
    "mouse/state",
    "mouse",
    "mouse/raw",
)
_MODIFIER_FAMILIES = {
    16: (160, 161),
    17: (162, 163),
    18: (164, 165),
}
_IGNORED_PERSISTENT_VKS = frozenset({179})
_IGNORED_SNAPSHOT_VKS = _IGNORED_PERSISTENT_VKS | frozenset(_MODIFIER_FAMILIES)


def desktop_mcap_selected_topics(available_topics: tuple[str, ...] | list[str]) -> list[str]:
    """Return the exact topic filter whose iterator order defines native source_order."""

    return [
        *DESKTOP_MCAP_BASE_SELECTED_TOPICS,
        *(["window"] if "window" in available_topics else []),
    ]


def virtual_key_name(value: int) -> str:
    """Return the canonical key name used by desktop MCAP inputs."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("virtual key must be an integer")
    if 48 <= value <= 57:
        return chr(value)
    if 65 <= value <= 90:
        return chr(value).lower()
    if 112 <= value <= 135:
        return f"f{value - 111}"
    return _VIRTUAL_KEY_NAMES.get(value, f"vk_{value}")


def _frame_rate(value: Any) -> float:
    try:
        rate = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"{_SOURCE_LABEL} video has an invalid frame rate: {value!r}") from error
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError(f"{_SOURCE_LABEL} video has an invalid frame rate: {value!r}")
    return rate


def _screen_source_shape(record: dict[str, Any]) -> tuple[int, int]:
    value = record.get("source_shape")
    if (
        not isinstance(value, (tuple, list))
        or len(value) != 2
        or any(isinstance(component, bool) or not isinstance(component, int) or component <= 0 for component in value)
    ):
        raise ValueError(f"{_SOURCE_LABEL} screen record has an invalid source_shape: {value!r}")
    return int(value[0]), int(value[1])


def _probe_video_decode(video_path: Path, timestamp_ms: float) -> None:
    ffmpeg = resolve_ffmpeg()
    try:
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-ss",
                f"{max(timestamp_ms, 0.0) / 1_000:.6f}",
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"{_SOURCE_LABEL} paired video failed the decode probe: {detail}") from error


def _decode_payload(message: Any) -> dict[str, Any]:
    """Decode once using OWA's dictionary decoder, without its shared cached-property lock."""
    from mcap_owa.decode_utils import dict_decoder

    return dict(dict_decoder(message.message))


def _decoded_message(
    reader: Any,
    topic: str,
    *,
    start_time: int | None = None,
    end_time: int | None = None,
    reverse: bool = False,
) -> tuple[int, dict[str, Any]] | None:
    messages = reader.iter_messages(
        topics=[topic],
        start_time=start_time,
        end_time=end_time,
        reverse=reverse,
    )
    message = next(messages, None)
    if message is None:
        return None
    return int(message.timestamp), _decode_payload(message)


def _nearest_screen_index(screen_times_ms: list[float], requested_ms: float) -> int | None:
    index = bisect.bisect_left(screen_times_ms, requested_ms)
    candidates = [candidate for candidate in (index - 1, index) if 0 <= candidate < len(screen_times_ms)]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda candidate: abs(screen_times_ms[candidate] - requested_ms))
    return nearest if abs(screen_times_ms[nearest] - requested_ms) <= _MAX_SCREEN_FRAME_ALIGNMENT_ERROR_MS else None


def _has_required_screen_context(
    screen_times_ms: list[float],
    anchor_video_time_ms: float,
) -> bool:
    return all(
        _nearest_screen_index(screen_times_ms, anchor_video_time_ms + offset_ms) is not None
        for offset_ms in (0, ACTION_DURATION_MS)
    )


def _desktop_mcap_anchor_indices(
    screen_times_ms: list[float],
    action_times_ms: list[float],
    *,
    session_video_time_bounds_ms: tuple[float, float],
    video_duration_ms: float,
    config: SamplingConfig,
    capture_geometry_action_range_ms: tuple[float, float] | None,
    require_frame_context: bool = True,
) -> list[int]:
    first_index = 0
    last_index = len(screen_times_ms) - 1
    session_first_video_time_ms, session_last_video_time_ms = session_video_time_bounds_ms
    start_ms = max(config.start_time_ms, session_first_video_time_ms)
    end_ms = min(session_last_video_time_ms, video_duration_ms) - 2 * ACTION_DURATION_MS
    if capture_geometry_action_range_ms is not None:
        scope_start_ms, scope_end_ms = capture_geometry_action_range_ms
        start_ms = max(
            start_ms,
            float(scope_start_ms) - _MAX_SCREEN_FRAME_ALIGNMENT_ERROR_MS,
        )
        end_ms = min(
            end_ms,
            float(scope_end_ms) - ACTION_DURATION_MS + _MAX_SCREEN_FRAME_ALIGNMENT_ERROR_MS,
        )
    if end_ms < start_ms:
        return []

    result: list[int] = []
    previous_frame_index: int | None = None
    for time_ms in iter_sample_times(
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        max_samples=None,
    ):
        frame_index = bisect.bisect_left(action_times_ms, time_ms)
        frame_index = min(max(frame_index, first_index), last_index)
        if frame_index == previous_frame_index:
            continue
        previous_frame_index = frame_index
        if require_frame_context and not _has_required_screen_context(
            screen_times_ms, screen_times_ms[frame_index]
        ):
            continue
        result.append(frame_index)
    return result


def _validate_capture_geometry_action_range(action_range_ms: tuple[float, float]) -> tuple[float, float]:
    if (
        not isinstance(action_range_ms, tuple)
        or len(action_range_ms) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in action_range_ms)
    ):
        raise ValueError("capture_geometry_action_range_ms must contain two numeric values")
    start_ms, end_ms = (float(value) for value in action_range_ms)
    if not math.isfinite(start_ms) or not math.isfinite(end_ms) or start_ms < 0 or end_ms <= start_ms:
        raise ValueError("capture_geometry_action_range_ms must be a finite increasing nonnegative range")
    return start_ms, end_ms


@dataclass(frozen=True)
class ScreenFrame:
    source_index: int
    log_ns: int
    pts_ns: int
    shape: tuple[int, int]
    uri: str


def _screen_pts_ns(record):
    try:
        value = record["media_ref"]["pts_ns"]
        if not isinstance(value, (int, float, str)) or isinstance(value, bool):
            raise TypeError
        number = float(value)
    except (KeyError, OverflowError, TypeError, ValueError) as error:
        raise SourceQualificationError(
            f"{_SOURCE_LABEL} screen MediaRef is missing a numeric pts_ns",
            reason_code="source_frame_identity_invalid",
            evidence={"field": "screen.media_ref.pts_ns", "issue": "missing_or_non_numeric"},
        ) from error
    if not math.isfinite(number) or number < 0:
        raise SourceQualificationError(
            f"{_SOURCE_LABEL} screen MediaRef has an invalid pts_ns",
            reason_code="source_frame_identity_invalid",
            evidence={"field": "screen.media_ref.pts_ns", "issue": "non_finite_or_negative"},
        )
    return value if isinstance(value, int) else round(number)


def _screen_frame(timestamp_ns, payload, source_index):
    return ScreenFrame(
        source_index,
        timestamp_ns,
        _screen_pts_ns(payload),
        _screen_source_shape(payload),
        str((payload.get("media_ref") or {}).get("uri") or "").replace("\\", "/"),
    )


def normalize_screen_frames(frames):
    """Retain source indices on the monotonic D2E message clock."""
    if not frames:
        raise ValueError(f"{_SOURCE_LABEL} session has no screen MediaRef timeline")
    if any(b.log_ns < a.log_ns for a, b in zip(frames, frames[1:])):
        raise ValueError("screen message log timeline is not monotonic")
    return list(frames)


def validate_desktop_mcap_video_identity(
    video_info, frames, video_path, *, identity_frames=None, geometry_frames=None, window_scoped=False
):
    """Validate source/video binding once; retain no parallel success-report schema."""
    identity_frames = identity_frames if identity_frames is not None else frames
    geometry_frames = geometry_frames if geometry_frames is not None else identity_frames
    if not frames or not identity_frames or not geometry_frames:
        raise ValueError("Screen identity and capture-geometry records are required")
    shapes = {f.shape for f in geometry_frames}
    scoped = window_scoped
    if len(shapes) != 1:
        diagnostic = f"{_SOURCE_LABEL} capture-geometry scope must declare one source_shape: {sorted(shapes)!r}"
        if scoped:
            raise SourceQualificationError(
                diagnostic,
                reason_code="capture_geometry_scope_ambiguous",
                evidence={"source_shapes": [list(s) for s in sorted(shapes)]},
            )
        raise ValueError(diagnostic)
    if {f.uri for f in identity_frames} != {video_path.name}:
        raise ValueError(f"{_SOURCE_LABEL} screen MediaRef must name the paired video exactly: {video_path.name}")
    if any(b.log_ns < a.log_ns or b.pts_ns < a.pts_ns for a, b in zip(frames, frames[1:])):
        raise ValueError(f"{_SOURCE_LABEL} screen message/MediaRef timeline is not monotonic")
    if max(abs(f.log_ns - f.pts_ns) for f in frames) > 50_000_000:
        raise ValueError(f"{_SOURCE_LABEL} screen message/MediaRef alignment exceeds 50 ms")
    stream = video_info.get("stream") or {}
    try:
        width, height = int(stream["width"]), int(stream["height"])
        duration_ms = float(video_info["format"]["duration"]) * 1000
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{_SOURCE_LABEL} video probe is missing encoded dimensions or duration") from error
    if width <= 0 or height <= 0:
        raise ValueError(f"{_SOURCE_LABEL} video has invalid encoded dimensions")
    _frame_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    if not str(stream.get("codec_name") or "").strip():
        raise ValueError(f"{_SOURCE_LABEL} video probe is missing codec_name")
    sw, sh = next(iter(shapes))
    if (width, height) != (sw, sh):
        diagnostic = f"{_SOURCE_LABEL} MCAP source_shape does not match the encoded video: {(sw, sh)} vs {(width, height)}"
        if scoped:
            raise SourceQualificationError(
                diagnostic,
                reason_code="capture_geometry_video_mismatch",
                evidence={
                    "source_shape": [sw, sh],
                    "encoded_shape": [width, height],
                },
            )
        raise ValueError(diagnostic)
    if identity_frames[0].pts_ns < 0 or identity_frames[-1].pts_ns / 1e6 > duration_ms + 50:
        raise ValueError(f"{_SOURCE_LABEL} screen timeline is not covered by the paired video")


@dataclass(frozen=True)
class _McapRead:
    records: dict[str, list[dict[str, Any]]]
    frames: list[ScreenFrame]
    first: ScreenFrame
    last: ScreenFrame


def _read_records(reader, topics, *, start=None, end=None, index=None, screen_cache=None):
    """Decode each selected record into one authoritative integer-clock representation."""
    source_offset = index.count_before(topics, start) if index is not None else 0
    screen_index = index.count_before(("screen",), start) if index is not None else 0
    records = defaultdict(list)
    frames = []
    for order, message in enumerate(reader.iter_messages(topics=topics, start_time=start, end_time=end)):
        stamp = int(message.timestamp)
        if message.topic == "screen":
            frame = screen_cache.get(screen_index) if screen_cache is not None else None
            if frame is None:
                frame = _screen_frame(stamp, _decode_payload(message), screen_index)
            frames.append(frame)
            screen_index += 1
        else:
            records[message.topic].append(
                {
                    "source_order": source_offset + order,
                    "topic": message.topic,
                    "timestamp_ns": stamp,
                    "payload": _decode_payload(message),
                }
            )
    return dict(records), frames


def _read_screen(reader, *, start=None, end=None, reverse=False, source_index=0):
    record = _decoded_message(reader, "screen", start_time=start, end_time=end, reverse=reverse)
    return _screen_frame(record[0], record[1], source_index) if record is not None else None


def _screen_scope_requirements(
    frames,
    *,
    origin_ns,
    session_video_time_bounds_ms,
    video_duration_ms,
    config,
    capture_geometry_action_range_ms,
):
    if not frames:
        return False, False, False
    if config.max_samples is None:
        return True, False, False
    frames = normalize_screen_frames(frames)
    video_times = [f.log_ns / 1e6 for f in frames]
    relative_times = [(f.log_ns - origin_ns) / 1e6 for f in frames]
    anchors = _desktop_mcap_anchor_indices(
        video_times,
        relative_times,
        session_video_time_bounds_ms=session_video_time_bounds_ms,
        video_duration_ms=video_duration_ms,
        config=config,
        capture_geometry_action_range_ms=capture_geometry_action_range_ms,
        require_frame_context=False,
    )
    need_start = need_end = False
    missing = len(anchors) < config.max_samples
    for frame_index in anchors[: config.max_samples]:
        for offset in (0, ACTION_DURATION_MS):
            requested = video_times[frame_index] + offset
            outside_start = requested - _MAX_SCREEN_FRAME_ALIGNMENT_ERROR_MS < video_times[0]
            outside_end = requested + _MAX_SCREEN_FRAME_ALIGNMENT_ERROR_MS > video_times[-1]
            need_start = need_start or outside_start
            need_end = need_end or outside_end
            if not outside_start and not outside_end and _nearest_screen_index(video_times, requested) is None:
                missing = True
    return not missing and not need_start and not need_end, need_start, need_end


def _bounded_screen_log_range(reader, *, index, first, last, video_duration_ms, config, action_range_ms):
    start_ms, end_ms = action_range_ms
    tolerance = round(_MAX_SCREEN_FRAME_ALIGNMENT_ERROR_MS * 1e6)
    left = max(first.log_ns, first.log_ns + round(start_ms * 1e6) - tolerance)
    right = min(last.log_ns + 1, first.log_ns + round(end_ms * 1e6) + tolerance + 1)
    bounds = (first.log_ns / 1e6, last.log_ns / 1e6)
    cache = {}
    while True:
        # Reuse parsed screen frames while expanding only missing context edges.
        _, frames = _read_records(
            reader, ["screen"], start=left, end=right, index=index, screen_cache=cache
        )
        cache.update((f.source_index, f) for f in frames)
        closed, need_left, need_right = _screen_scope_requirements(
            frames,
            origin_ns=first.log_ns,
            session_video_time_bounds_ms=bounds,
            video_duration_ms=video_duration_ms,
            config=config,
            capture_geometry_action_range_ms=action_range_ms,
        )
        if not frames:
            raise SourceQualificationError(
                "desktop MCAP has no screen messages in the requested trajectory context",
                reason_code="source_frame_context_missing",
                evidence={"action_range_ms": [start_ms, end_ms]},
            )
        if closed or not (need_left or need_right):
            return left, right, cache
        growth = max(5_000_000_000, right - left)
        new_left = max(first.log_ns, left - growth) if need_left else left
        new_right = min(last.log_ns + 1, right + growth) if need_right else right
        if (new_left, new_right) == (left, right):
            return left, right, cache
        left, right = new_left, new_right


def _bounded_desktop_mcap_read(reader, mcap_path, selected_topics, action_range_ms, *, config, video_duration_ms):
    start_ms, end_ms = _validate_capture_geometry_action_range(action_range_ms)
    index = desktop_mcap_session_index(mcap_path)
    first = _read_screen(reader, source_index=0)
    last = _read_screen(reader, reverse=True, source_index=index.topic_count("screen") - 1)
    if first is None or last is None:
        raise ValueError(f"desktop MCAP session has no screen messages: {mcap_path}")
    scope_start = first.log_ns + round(start_ms * 1e6)
    scope_end = first.log_ns + round(end_ms * 1e6)
    screen_start, screen_end, cache = _bounded_screen_log_range(
        reader,
        index=index,
        first=first,
        last=last,
        video_duration_ms=video_duration_ms,
        config=config,
        action_range_ms=(start_ms, end_ms),
    )
    candidates = [screen_start]
    for state_topic, event_topic in (("keyboard/state", "keyboard"), ("mouse/state", "mouse")):
        seed = (
            _decoded_message(reader, state_topic, end_time=scope_start + 1, reverse=True)
            if state_topic in reader.topics
            else None
        )
        if seed is not None:
            candidates.append(seed[0])
        else:
            stamp = index.first_timestamp((event_topic,))
            if stamp is not None:
                candidates.append(stamp)
    mouse = _decoded_message(reader, "mouse", end_time=scope_start + 1, reverse=True)
    if mouse is not None:
        candidates.append(mouse[0])
    start, end = min(candidates), max(scope_end + 1, screen_end)
    records, frames = _read_records(
        reader, selected_topics, start=start, end=end, index=index, screen_cache=cache
    )
    if "window" in reader.topics:
        seed = _decoded_message(reader, "window", end_time=scope_start + 1, reverse=True)
        if seed is not None and seed[0] < start:
            records.setdefault("window", []).insert(
                0,
                {
                    "timestamp_ns": seed[0],
                    "topic": "window",
                    "payload": seed[1],
                },
            )
    return _McapRead(records, frames, first, last)


def _window_geometry_frames(frames, origin_ns, action_range_ms):
    start, end = _validate_capture_geometry_action_range(action_range_ms)
    chosen = [f for f in frames if max(0, start - 50) <= (f.log_ns - origin_ns) / 1e6 <= end + 50]
    if not chosen:
        raise SourceQualificationError(
            "desktop MCAP capture-geometry action range has no screen records",
            reason_code="capture_geometry_scope_empty",
            evidence={"requested_action_start_ms": start, "requested_action_end_ms": end, "selection_tolerance_ms": 50},
        )
    return chosen


class D2EAdapter:
    """Paired desktop recordings with one integer input clock and an explicit video clock."""

    action_provenance = "raw_hid"
    source_native_onset_owner_policy = ANCHOR_INTERVAL_ONSET_OWNER

    def __init__(
        self,
        mcap_path: Path,
        video_path: Path | None = None,
        *,
        source_revision: str = "local",
        capture_geometry_action_range_ms: tuple[float, float] | None = None,
        bounded_read_config: SamplingConfig | None = None,
    ):
        try:
            from mcap_owa.highlevel import OWAMcapReader
        except ImportError as error:
            raise RuntimeError(
                f"{_SOURCE_LABEL} decoding requires mcap-owa-support and owa-msgs"
            ) from error
        self.mcap_path = mcap_path.expanduser().resolve()
        self.video_path = (video_path or self.mcap_path.with_suffix(".mkv")).expanduser().resolve()
        if not self.mcap_path.is_file() or not self.video_path.is_file():
            raise FileNotFoundError(f"{_SOURCE_LABEL} requires paired MCAP and video: {self.mcap_path}")
        if capture_geometry_action_range_ms is not None and bounded_read_config is None:
            raise ValueError(f"{_SOURCE_LABEL} does not allow window-scoped capture geometry")
        if bounded_read_config is not None and capture_geometry_action_range_ms is None:
            raise ValueError("A bounded read requires both its sampling config and capture-geometry range")
        self.capture_geometry_action_range_ms = capture_geometry_action_range_ms
        self.video_info = probe_immutable_source_video(self.video_path)
        self.video_duration_ms = float(self.video_info["format"]["duration"]) * 1000
        with OWAMcapReader(self.mcap_path, decode_args={"return_dict": True, "return_dict_on_failure": True}) as reader:
            self.topics = tuple(reader.topics)
            topics = desktop_mcap_selected_topics(self.topics)
            if capture_geometry_action_range_ms is not None:
                result = _bounded_desktop_mcap_read(
                    reader,
                    self.mcap_path,
                    topics,
                    capture_geometry_action_range_ms,
                    config=bounded_read_config,
                    video_duration_ms=self.video_duration_ms,
                )
            else:
                records, frames = _read_records(reader, topics)
                if not frames:
                    raise ValueError("MCAP session has no screen MediaRef timeline")
                result = _McapRead(records, frames, frames[0], frames[-1])
        self.records = result.records
        self.record_times = {topic: [r["timestamp_ns"] for r in rows] for topic, rows in self.records.items()}
        self.screens = normalize_screen_frames(result.frames)
        self.screen_positions = {frame.source_index: i for i, frame in enumerate(self.screens)}
        self.video_times_ms = [f.log_ns / 1e6 for f in self.screens]
        self.origin_ns = result.first.log_ns
        self.session_video_time_bounds_ms = (
            result.first.log_ns / 1e6,
            result.last.log_ns / 1e6,
        )
        geometry = result.frames
        identity = self.screens
        if capture_geometry_action_range_ms is not None:
            geometry = _window_geometry_frames(self.screens, self.origin_ns, capture_geometry_action_range_ms)
            identity = [result.first, *result.frames, result.last]
        validate_desktop_mcap_video_identity(
            self.video_info,
            self.screens,
            self.video_path,
            identity_frames=identity,
            geometry_frames=geometry,
            window_scoped=capture_geometry_action_range_ms is not None,
        )
        _probe_video_decode(self.video_path, self.video_times_ms[0])
        self.session = SourceSession(
            dataset_id=DATASET_ID,
            source_revision=source_revision,
            session_id=self.mcap_path.stem,
            game=self.mcap_path.parent.name.replace("_", " "),
            source_files=(self.mcap_path, self.video_path),
            source_metadata={"source_shape": geometry[0].shape},
        )

    def iter_anchors(self, config: SamplingConfig):
        indices = _desktop_mcap_anchor_indices(
            self.video_times_ms,
            self.video_times_ms,
            session_video_time_bounds_ms=self.session_video_time_bounds_ms,
            video_duration_ms=self.video_duration_ms,
            config=config,
            capture_geometry_action_range_ms=self.capture_geometry_action_range_ms,
        )
        for index in indices[: config.max_samples]:
            frame = self.screens[index]
            yield SampleAnchor(video_time_ms=self.video_times_ms[index], source_index=frame.source_index)

    def _screen(self, source_index):
        if (
            isinstance(source_index, bool)
            or not isinstance(source_index, int)
            or source_index not in self.screen_positions
        ):
            raise ValueError("desktop MCAP action clock requires a bound screen source_index")
        return self.screens[self.screen_positions[source_index]]

    def materialize_frame(self, anchor, relative_time_ms, output_root, *, resize):
        frame_index = _nearest_screen_index(self.video_times_ms, anchor.video_time_ms + relative_time_ms)
        if frame_index is None:
            return None
        frame = self.screens[frame_index]
        picture = MaterializedFrame(
            output_root / "frames" / resize.cache_directory / f"frame-{frame.source_index:08d}.jpg",
            self.video_times_ms[frame_index],
        )
        if not _is_nonempty_file(picture.path):
            extract_video_frame(self.video_path, picture.video_time_ms, picture.path, resize=resize)
        return picture

    def _records_between(self, topic, start_ns, end_ns):
        times = self.record_times.get(topic, [])
        return self.records.get(topic, [])[bisect.bisect_left(times, start_ns) : bisect.bisect_left(times, end_ns)]

    def _payloads_between(self, topic, start_ns, end_ns):
        return [r["payload"] for r in self._records_between(topic, start_ns, end_ns)]

    def _native_cursor_record_at(self, timestamp_ns):
        candidate = None
        for topic in ("mouse/state", "mouse"):
            index = bisect.bisect_right(self.record_times.get(topic, []), timestamp_ns) - 1
            if index >= 0:
                record = self.records[topic][index]
                if "x" in record["payload"] and (
                    candidate is None or record["timestamp_ns"] > candidate["timestamp_ns"]
                ):
                    candidate = record
        return candidate

    def _window_records(self, start_ns, end_ns):
        times = self.record_times.get("window", [])
        first = bisect.bisect_right(times, start_ns) - 1
        last = bisect.bisect_left(times, end_ns)
        return self.records.get("window", [])[max(0, first) : last]

    def source_native_action_clock_ns(self, anchor):
        return self._screen(anchor.source_index).log_ns

    def observation_geometry(self, anchor):
        width, height = self.session.source_metadata["source_shape"]
        return {"width_px": width, "height_px": height, "source": "screen.source_shape"}

    def gui_events(self):
        """Read exact D2E input events within the recorded screen timeline.

        Foreground changes break the episode. Mouse press records own targets.
        """
        logs = [f.log_ns for f in self.screens]
        width, height = self.session.source_metadata["source_shape"]
        output = []
        known_modifiers = set()
        records = sorted(
            (record for topic in ("mouse", "keyboard", "keyboard/state") for record in self.records.get(topic, [])),
            key=lambda r: r["source_order"],
        )
        for record in records:
            stamp = record["timestamp_ns"]
            i = bisect.bisect_right(logs, stamp) - 1
            if i < 0 or i + 1 >= len(logs):
                continue
            if logs[i + 1] <= logs[i]:
                continue
            locator = {
                "source_order": record["source_order"],
                "topic": record["topic"],
                "log_time_ns": stamp,
                "screen_log_bounds_ns": [logs[i], logs[i + 1]],
                "screen_pts_bounds_ns": [logs[i], logs[i + 1]],
            }
            value = record["payload"]

            def add(kind, **data):
                output.append(Event(stamp, kind, data, locator))

            if record["topic"] == "keyboard/state":
                state = {
                    virtual_key_name(int(vk)) for vk in value.get("buttons", []) if int(vk) not in _IGNORED_SNAPSHOT_VKS
                }
                state_modifiers = state & MODIFIERS
                for key in sorted(state_modifiers ^ known_modifiers):
                    add("modifier", key=key, down=key in state_modifiers)
                known_modifiers = state_modifiers
                add("keyboard_state", keys=sorted(state - MODIFIERS - {"left", "right", "middle"}))
                continue
            if record["topic"] == "keyboard":
                if int(value["vk"]) in _IGNORED_PERSISTENT_VKS:
                    continue
                key = virtual_key_name(int(value["vk"]))
                if key in MODIFIERS:
                    down = value["event_type"] == "press"
                    if down != (key in known_modifiers):
                        add("modifier", key=key, down=down)
                    if down:
                        known_modifiers.add(key)
                    else:
                        known_modifiers.discard(key)
                else:
                    add("modifier_state", keys=sorted(known_modifiers))
                    add("key_down" if value["event_type"] == "press" else "key_up", key=key)
                continue
            try:
                point = position(float(value["x"]), float(value["y"]), width, height)
            except (ValueError, KeyError, TypeError):
                add("boundary", reason="cursor position unavailable")
                continue
            kind = value["event_type"]
            if kind == "move":
                add("move", position=point)
            elif kind == "click":
                button = canonical_mouse_button_name(value["button"])
                if button not in {"left", "right", "middle"}:
                    add("boundary", reason="unsupported mouse button")
                else:
                    if value["pressed"]:
                        add("modifier_state", keys=sorted(known_modifiers))
                    add("press" if value["pressed"] else "release", button=button, position=point)
            elif kind == "scroll":
                add("modifier_state", keys=sorted(known_modifiers))
                add("move", position=point)
                add(
                    "scroll",
                    dx=value["dx"],
                    dy=pixel_scroll_dy(value["dy"], "mcap_scroll_delta"),
                    unit="scroll_pixel_delta",
                )
            else:
                add("boundary", reason="unknown semantic mouse input")
        # A foreground change is a hard boundary regardless of the surrounding seed.
        last_window = None
        for record in self.records.get("window", []):
            payload = record["payload"]
            token = (
                payload.get("hWnd"),
                payload.get("title"),
                tuple(payload.get("rect", [])),
                payload.get("is_foreground", payload.get("focused", True)),
            )
            if token == last_window:
                continue
            last_window = token
            stamp = record["timestamp_ns"]
            i = bisect.bisect_right(logs, stamp) - 1
            if 0 <= i < len(logs) - 1 and logs[i + 1] > logs[i]:
                output.append(
                    Event(
                        stamp,
                        "boundary",
                        {"reason": "foreground window event"},
                        {"topic": "window", "log_time_ns": stamp},
                    )
                )
        return sorted(output, key=lambda event: event.time_ns)

    def _check_window(
        self,
        anchor: SampleAnchor,
        interval: SourceActionInterval,
    ) -> None:
        """Collect source-evidence diagnostics independently of an action-space projection."""

        reasons: list[str] = []
        start, end = interval.start_ns, interval.end_ns
        records = self._window_records(start, end)
        if not records or records[0]["timestamp_ns"] > start:
            reasons.append("foreground_window_unverified")

        source_shape = self.session.source_metadata.get("source_shape")
        geometry_valid = (
            isinstance(source_shape, (list, tuple))
            and len(source_shape) == 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in source_shape)
            and all(math.isfinite(float(value)) and float(value) > 0 for value in source_shape)
        )
        if not geometry_valid:
            reasons.append("capture_geometry_invalid")
        expected_title = "".join(character for character in self.session.game.casefold() if character.isalnum())
        for native_record in records:
            record = native_record["payload"]
            title = record.get("title")
            normalized_title = "".join(character for character in str(title or "").casefold() if character.isalnum())
            if not normalized_title or not expected_title or not (
                expected_title in normalized_title or normalized_title in expected_title
            ):
                reasons.append("foreground_window_title_mismatch")
            if not isinstance(record.get("hWnd"), int) or record["hWnd"] <= 0:
                reasons.append("foreground_window_focus_unverified")
            if any(
                field in record and not bool(record[field])
                for field in ("focused", "is_focused", "isForeground", "is_foreground")
            ):
                reasons.append("foreground_window_not_focused")

            rect = record.get("rect")
            rect_valid = (
                isinstance(rect, (list, tuple))
                and len(rect) == 4
                and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in rect)
                and all(math.isfinite(float(value)) for value in rect)
                and float(rect[2]) > float(rect[0])
                and float(rect[3]) > float(rect[1])
            )
            if not rect_valid:
                reasons.append("foreground_window_geometry_invalid")
            elif geometry_valid:
                left, top, right, bottom = (float(value) for value in rect)
                width, height = (float(value) for value in source_shape)
                if (
                    abs(left) > 1.0
                    or abs(top) > 1.0
                    or abs((right - left) - width) > 1.0
                    or abs((bottom - top) - height) > 1.0
                ):
                    reasons.append("foreground_window_geometry_mismatch")

        if reasons:
            raise ValueError(
                f"Source action window rejected: {list(dict.fromkeys(reasons))}; source_interval_ns={[start, end]}"
            )

    def pointer_samples(self, anchor: SampleAnchor, interval: SourceActionInterval) -> list[dict]:
        if interval.anchor_ns != self.source_native_action_clock_ns(anchor):
            raise ValueError("desktop MCAP source interval differs from its anchor clock")
        self._check_window(anchor, interval)
        start, end = interval.start_ns, interval.end_ns
        keyboard = [
            r
            for r in self._records_between("keyboard", start, end)
            if int(r["payload"]["vk"]) not in _IGNORED_PERSISTENT_VKS
        ]
        mouse = self._records_between("mouse", start, end)
        # Preserve recorder substeps for motion/scroll aggregation and cursor precedence.
        boundaries = {0, interval.duration_ns}
        boundaries.update(range(50_000_000, interval.duration_ns, 50_000_000))
        boundaries.update(r["timestamp_ns"] - start for r in keyboard)
        boundaries.update(r["timestamp_ns"] - start for r in mouse if r["payload"].get("event_type") == "click")
        points = sorted(boundaries)
        samples = []
        for left, right in zip(points, points[1:]):
            left_ns, right_ns = interval.start_ns + left, interval.start_ns + right
            raw = self._payloads_between("mouse/raw", left_ns, right_ns)
            for event in raw:
                if any(
                    isinstance(event.get(k, 0), bool) or not isinstance(event.get(k, 0), int)
                    for k in ("last_x", "last_y")
                ):
                    raise ValueError("raw HID deltas must be integers")
            dx, dy = sum(e.get("last_x", 0) for e in raw), sum(e.get("last_y", 0) for e in raw)
            sample = {}
            if dx or dy:
                sample["mouse_delta"] = {"dx": dx, "dy": dy, "space": "raw_hid_counts"}
            cursor = self._native_cursor_record_at(left_ns)
            if cursor is not None:
                sample["cursor"] = {"x": cursor["payload"]["x"], "y": cursor["payload"]["y"], "space": "screen_pixels"}
            wheels = [e for e in self._payloads_between("mouse", left_ns, right_ns) if e.get("event_type") == "scroll"]
            dx, dy = sum(e.get("dx", 0) for e in wheels), sum(e.get("dy", 0) for e in wheels)
            if dx or dy:
                sample["scroll"] = {"dx": dx, "dy": dy, "space": "wheel_ticks"}
            samples.append(sample)
        return samples

    def source_native_keyboard_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> KeyboardTimeline:
        """Return desktop-MCAP keyboard evidence on the integer message clock."""

        starts_ns = tuple(self.source_native_action_clock_ns(anchor) for anchor in anchors)
        lookaround_ns = 2_000_000_000
        margin_start_ns = starts_ns[0] - lookaround_ns
        state_records = self.records.get("keyboard/state", [])
        keyboard_records = []
        for record in self.records.get("keyboard", []):
            virtual_key = int(record["payload"]["vk"])
            if virtual_key in _MODIFIER_FAMILIES:
                raise ValueError("desktop MCAP aggregate modifier VK appeared as a keyboard edge")
            if virtual_key not in _IGNORED_PERSISTENT_VKS:
                keyboard_records.append(record)
        edge_times_ns = sorted(int(record["timestamp_ns"]) for record in keyboard_records)
        family_edge_times_ns = {
            aggregate_vk: sorted(
                int(record["timestamp_ns"]) for record in keyboard_records if int(record["payload"]["vk"]) in family_vks
            )
            for aggregate_vk, family_vks in _MODIFIER_FAMILIES.items()
        }

        def is_stable_seed(record: dict[str, Any]) -> bool:
            timestamp_ns = int(record["timestamp_ns"])
            first_nearby = bisect.bisect_left(
                edge_times_ns,
                timestamp_ns - _KEYBOARD_EDGE_WITNESS_TOLERANCE_NS,
            )
            return first_nearby >= len(edge_times_ns) or edge_times_ns[first_nearby] > (
                timestamp_ns + _KEYBOARD_EDGE_WITNESS_TOLERANCE_NS
            )

        seed_candidates = [
            record
            for record in state_records
            if int(record["timestamp_ns"]) <= margin_start_ns and is_stable_seed(record)
        ]
        if not seed_candidates:
            seed_candidates = [
                record
                for record in state_records
                if int(record["timestamp_ns"]) <= starts_ns[0] and is_stable_seed(record)
            ]
        if not seed_candidates:
            raise ValueError("desktop MCAP keyboard gesture reconstruction requires a stable keyboard/state seed")
        seed_record = seed_candidates[-1]

        last_screen_ns = self.screens[-1].log_ns
        requested_end_ns = starts_ns[-1] + round(float(horizon_ms) * 1_000_000) + lookaround_ns
        observed_end_ns = min(requested_end_ns, last_screen_ns)

        def state(record: dict[str, Any]) -> KeyboardState:
            timestamp_ns = int(record["timestamp_ns"])
            raw_virtual_keys = {int(value) for value in record["payload"].get("buttons", [])}
            for aggregate_vk, family_vks in _MODIFIER_FAMILIES.items():
                aggregate_present = aggregate_vk in raw_virtual_keys
                physical_present = bool(raw_virtual_keys.intersection(family_vks))
                if aggregate_present == physical_present:
                    continue
                family_times = family_edge_times_ns[aggregate_vk]
                nearby = bisect.bisect_left(
                    family_times,
                    timestamp_ns - _KEYBOARD_EDGE_WITNESS_TOLERANCE_NS,
                )
                if nearby >= len(family_times) or family_times[nearby] > (
                    timestamp_ns + _KEYBOARD_EDGE_WITNESS_TOLERANCE_NS
                ):
                    raise ValueError("desktop MCAP modifier aggregate snapshot disagrees with its physical keys")
            virtual_keys = sorted(raw_virtual_keys - _IGNORED_SNAPSHOT_VKS)
            return KeyboardState(
                timestamp_ns=timestamp_ns,
                source_order=int(record["source_order"]),
                keys=tuple(
                    KeyboardKey(identity=f"vk:{virtual_key}", key=virtual_key_name(virtual_key))
                    for virtual_key in virtual_keys
                ),
            )

        def edge(record: dict[str, Any]) -> KeyboardEdge:
            virtual_key = int(record["payload"]["vk"])
            event_type = record["payload"].get("event_type")
            if event_type not in {"press", "release"}:
                raise ValueError("desktop MCAP keyboard edge event_type must be press or release")
            return KeyboardEdge(
                timestamp_ns=int(record["timestamp_ns"]),
                source_order=int(record["source_order"]),
                identity=f"vk:{virtual_key}",
                key=virtual_key_name(virtual_key),
                pressed=event_type == "press",
            )

        seed = state(seed_record)
        checkpoints = tuple(
            state(record)
            for record in state_records
            if seed.source_order < int(record["source_order"]) and int(record["timestamp_ns"]) <= observed_end_ns
        )
        edges = tuple(
            edge(record)
            for record in keyboard_records
            if seed.source_order < int(record["source_order"]) and int(record["timestamp_ns"]) <= observed_end_ns
        )
        keyboard_topic_available = "keyboard" in self.topics
        if not keyboard_topic_available:
            raise ValueError("desktop MCAP keyboard gesture reconstruction requires exact keyboard edges")
        return KeyboardTimeline(
            authority=D2E_INPUT_PROFILE,
            evidence_kind="exact_edges",
            window_starts_ns=starts_ns,
            seed=seed,
            checkpoints=checkpoints,
            edges=edges,
            observed_end_ns=observed_end_ns,
            onset_owner_policy=self.source_native_onset_owner_policy,
        )

    def source_native_mouse_button_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> ExactMouseButtonTimeline:
        """Return exact desktop-MCAP button edges on the integer message clock."""

        starts_ns = tuple(self.source_native_action_clock_ns(anchor) for anchor in anchors)
        lookaround_ns = 2_000_000_000
        margin_start_ns = starts_ns[0] - lookaround_ns
        state_records = self.records.get("mouse/state", [])
        semantic_mouse_records = [
            record for record in self.records.get("mouse", []) if record["payload"].get("event_type") == "click"
        ]
        raw_button_records = [
            record
            for record in self.records.get("mouse/raw", [])
            if any(int(record["payload"].get("button_flags", 0)) & flag for flag, _, _ in _RAW_MOUSE_BUTTON_FLAGS)
        ]
        button_edge_times_ns = sorted(
            int(record["timestamp_ns"]) for record in (*semantic_mouse_records, *raw_button_records)
        )

        def is_stable_seed(record: dict[str, Any]) -> bool:
            timestamp_ns = int(record["timestamp_ns"])
            first_nearby = bisect.bisect_left(
                button_edge_times_ns,
                timestamp_ns - _MOUSE_EDGE_WITNESS_TOLERANCE_NS,
            )
            return first_nearby >= len(button_edge_times_ns) or button_edge_times_ns[first_nearby] > (
                timestamp_ns + _MOUSE_EDGE_WITNESS_TOLERANCE_NS
            )

        seed_candidates = [
            record
            for record in state_records
            if int(record["timestamp_ns"]) <= margin_start_ns and is_stable_seed(record)
        ]
        if not seed_candidates:
            seed_candidates = [
                record
                for record in state_records
                if int(record["timestamp_ns"]) <= starts_ns[0] and is_stable_seed(record)
            ]
        if not seed_candidates:
            raise ValueError(
                f"{_SOURCE_LABEL} mouse gesture reconstruction requires a stable mouse/state seed"
            )
        seed_record = seed_candidates[-1]

        last_screen_ns = self.screens[-1].log_ns
        requested_end_ns = starts_ns[-1] + round(float(horizon_ms) * 1_000_000) + lookaround_ns
        observed_end_ns = min(requested_end_ns, last_screen_ns)

        def state(record: dict[str, Any]) -> MouseButtonState:
            return MouseButtonState(
                timestamp_ns=int(record["timestamp_ns"]),
                source_order=int(record["source_order"]),
                buttons=frozenset(
                    canonical_mouse_button_name(button) for button in record["payload"].get("buttons", [])
                ),
            )

        def edge(record: dict[str, Any]) -> MouseButtonEdge:
            pressed = record["payload"]["pressed"]
            if not isinstance(pressed, bool):
                raise ValueError(f"{_SOURCE_LABEL} mouse click edge pressed must be boolean")
            return MouseButtonEdge(
                timestamp_ns=int(record["timestamp_ns"]),
                source_order=int(record["source_order"]),
                button=canonical_mouse_button_name(record["payload"]["button"]),
                pressed=pressed,
            )

        seed = state(seed_record)
        checkpoints = tuple(
            state(record)
            for record in state_records
            if seed.source_order < int(record["source_order"]) and int(record["timestamp_ns"]) <= observed_end_ns
        )
        edges = tuple(
            edge(record)
            for record in semantic_mouse_records
            if seed.source_order < int(record["source_order"]) and int(record["timestamp_ns"]) <= observed_end_ns
        )
        raw_edges = tuple(
            MouseButtonEdge(
                timestamp_ns=int(record["timestamp_ns"]),
                source_order=int(record["source_order"]),
                button=button,
                pressed=pressed,
            )
            for record in raw_button_records
            if seed.timestamp_ns - _MOUSE_EDGE_WITNESS_TOLERANCE_NS
            <= int(record["timestamp_ns"])
            <= observed_end_ns + _MOUSE_EDGE_WITNESS_TOLERANCE_NS
            for flag, button, pressed in _RAW_MOUSE_BUTTON_FLAGS
            if int(record["payload"].get("button_flags", 0)) & flag
        )
        return ExactMouseButtonTimeline(
            authority=D2E_INPUT_PROFILE,
            window_starts_ns=starts_ns,
            seed=seed,
            checkpoints=checkpoints,
            edges=edges,
            observed_end_ns=observed_end_ns,
            corroborating_edges=(raw_edges if "mouse/raw" in self.topics else None),
            onset_owner_policy=self.source_native_onset_owner_policy,
        )
