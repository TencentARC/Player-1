"""OpenAI VPT contractor 6.x/7.x adapter.

The public recorder stores one JSON action/state row per 20 Hz video step.  A
row describes the input held while advancing from video frame ``i`` to
``i + 1``.  The adapter keeps the original MP4 and JSONL as immutable source
evidence, derives only bounded 200 ms action windows, and never interprets GUI
cursor coordinates as Minecraft camera motion.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from fractions import Fraction
from functools import cached_property
from pathlib import Path
from typing import Any

from player1.agents.actions.devices import (
    STANDARD_MOUSE_BUTTONS,
)
from player1_data.files import _is_nonempty_file
from player1_data.sources.common import (
    ACTION_DURATION_MS,
    FrameResizeSpec,
    MaterializedFrame,
    SampleAnchor,
    SamplingConfig,
    SourceSession,
    canonical_key_name,
    extract_video_frame,
    probe_video,
)
from player1_data.standardize.gui import MODIFIERS, Event, position
from player1_data.standardize.keyboard import (
    KeyboardImpulse,
    KeyboardKey,
    KeyboardState,
    KeyboardTimeline,
)
from player1_data.standardize.mouse import (
    MouseButtonState,
    QuantizedMouseButtonTimeline,
)
from player1_data.standardize.temporal import (
    ANCHOR_INTERVAL_ONSET_OWNER,
    OnsetOwnerPolicy,
    SourceActionInterval,
)

DATASET_ID = "openai/vpt-contractor"
SOURCE_URL = "https://github.com/openai/Video-Pre-Training#contractor-demonstrations"
ACTION_SAMPLE_RATE_HZ = 20
ACTION_STEP_MS = 1_000.0 / ACTION_SAMPLE_RATE_HZ
MOUSE_DEGREES_PER_COUNT = 360.0 / 2_400.0
_GUI_STEP_NS = 50_000_000
_BUTTON_NAMES = {0: "left", 1: "right", 2: "middle"}
_KEY_PREFIX = "key.keyboard."
_SURROGATE_ESCAPE_MIN = 0xDC80
_SURROGATE_ESCAPE_MAX = 0xDCFF
_GESTURE_LOOKAROUND_NS = 2_000_000_000


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _canonical_vpt_key(value: Any) -> str:
    key = str(value).strip().lower()
    key = key.removeprefix(_KEY_PREFIX)
    key = {
        "left.shift": "shift",
        "right.shift": "shift",
        "left.control": "control",
        "right.control": "control",
        "left.alt": "alt",
        "right.alt": "alt",
    }.get(key, key)
    return canonical_key_name(key)


def _canonical_vpt_button(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return f"unsupported_{value!s}"
    return _BUTTON_NAMES.get(value, f"unsupported_{value}")


def _contains_surrogate_escape(value: Any) -> bool:
    if isinstance(value, str):
        return any(_SURROGATE_ESCAPE_MIN <= ord(character) <= _SURROGATE_ESCAPE_MAX for character in value)
    if isinstance(value, list):
        return any(_contains_surrogate_escape(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_surrogate_escape(key) or _contains_surrogate_escape(item) for key, item in value.items())
    return False


def _decode_vpt_jsonl_row(
    raw_line: bytes,
    *,
    path: Path,
    line_number: int,
    byte_offset: int,
) -> Any:
    """Decode one VPT row, repairing only the recorder's unused chars field."""

    try:
        decoded = raw_line.decode("utf-8")
    except UnicodeDecodeError as error:
        decoded = raw_line.decode("utf-8", errors="surrogateescape")
        try:
            raw = json.loads(decoded)
        except json.JSONDecodeError as parse_error:
            raise ValueError(
                f"VPT JSONL has non-UTF-8 bytes outside a valid JSON string at "
                f"{path}:{line_number} (byte {byte_offset + error.start})"
            ) from parse_error
        keyboard = raw.get("keyboard") if isinstance(raw, dict) else None
        chars = keyboard.get("chars") if isinstance(keyboard, dict) else None
        if not isinstance(chars, str) or not _contains_surrogate_escape(chars):
            raise ValueError(
                f"VPT JSONL has non-UTF-8 bytes outside keyboard.chars at "
                f"{path}:{line_number} (byte {byte_offset + error.start})"
            ) from error
        keyboard["chars"] = ""
        if _contains_surrogate_escape(raw):
            raise ValueError(
                f"VPT JSONL has non-UTF-8 bytes outside keyboard.chars at "
                f"{path}:{line_number} (byte {byte_offset + error.start})"
            ) from error
        return raw
    return json.loads(decoded)


class VPTContractorAdapter:
    """Normalize one paired VPT contractor MP4/JSONL segment."""

    action_provenance = "recorded_key_state"

    def gui_events(self):
        """Read the original recording into GUI events."""
        return vpt_events(self._gui_rows())

    def _gui_rows(self):
        return [
            dict(
                gui=row["is_gui_open"],
                x=row["x"],
                y=row["y"],
                wheel=row["dwheel"],
                buttons=set(row["raw_buttons"]) - ({0} if row["attack_stuck_repaired"] else set()),
                new_buttons=row["new_buttons"],
                keys=set(row["keys"]),
                chars=row["chars"],
                locator=row["locator"],
            )
            for row in self.rows
        ]

    @cached_property
    def _gui_exits(self):
        return tuple(
            (i, row["x"], row["y"])
            for i, row in enumerate(self.rows)
            if i and self.rows[i - 1]["is_gui_open"] and not row["is_gui_open"]
        )

    def check_gui_geometry(self, end_ns):
        if cursor_plane_conflict(self._gui_exits, end_ns):
            raise ValueError("VPT recorded cursor plane contradicts its nominal geometry")

    def __init__(
        self,
        jsonl_path: Path,
        video_path: Path | None = None,
        *,
        source_revision: str = "local",
    ) -> None:
        self.jsonl_path = jsonl_path.expanduser().resolve()
        self.video_path = (
            video_path.expanduser().resolve() if video_path is not None else self.jsonl_path.with_suffix(".mp4")
        )
        if not self.jsonl_path.is_file():
            raise FileNotFoundError(f"Missing VPT action JSONL: {self.jsonl_path}")
        if not self.video_path.is_file():
            raise FileNotFoundError(f"Missing VPT paired MP4: {self.video_path}")
        if self.video_path.stem != self.jsonl_path.stem:
            raise ValueError("VPT MP4 and JSONL must share one basename")
        self.rows = self._load_rows()
        if len(self.rows) < 2:
            raise ValueError(f"VPT segment has fewer than two action rows: {self.jsonl_path}")
        self._apply_official_stuck_attack_repair()
        self.video_probe = probe_video(self.video_path)
        self.video_frame_count = self._validate_video_contract()
        self.duration_ms = len(self.rows) * ACTION_STEP_MS

        recorder_version = self.jsonl_path.parent.name
        recorder_family = self.jsonl_path.parent.parent.name
        session_id = f"{recorder_family}-{recorder_version}-{self.jsonl_path.stem}"
        self.session = SourceSession(
            dataset_id=DATASET_ID,
            source_revision=source_revision,
            session_id=session_id,
            game="Minecraft",
            source_files=(self.jsonl_path, self.video_path),
            source_metadata={},
        )

    def _load_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        previous_tick: int | None = None
        byte_offset = 0
        with self.jsonl_path.open("rb") as source:
            for index, raw_line in enumerate(source):
                if not raw_line.strip():
                    raise ValueError(f"VPT JSONL contains a blank row at line {index + 1}")
                raw = _decode_vpt_jsonl_row(
                    raw_line,
                    path=self.jsonl_path,
                    line_number=index + 1,
                    byte_offset=byte_offset,
                )
                byte_offset += len(raw_line)
                if not isinstance(raw, dict):
                    raise ValueError(f"VPT JSONL row {index} must be an object")
                mouse = raw.get("mouse")
                keyboard = raw.get("keyboard")
                if not isinstance(mouse, dict) or not isinstance(keyboard, dict):
                    raise ValueError(f"VPT JSONL row {index} is missing mouse/keyboard state")
                tick = raw.get("tick")
                if isinstance(tick, bool) or not isinstance(tick, int):
                    raise ValueError(f"VPT JSONL row {index} has an invalid tick")
                if previous_tick is not None and tick != previous_tick + 1:
                    raise ValueError(f"VPT JSONL ticks are not contiguous at row {index}")
                previous_tick = tick
                keys = keyboard.get("keys")
                buttons = mouse.get("buttons")
                new_keys = keyboard.get("newKeys", [])
                new_buttons = mouse.get("newButtons", [])
                if not all(isinstance(value, list) for value in (keys, buttons, new_keys, new_buttons)):
                    raise ValueError(f"VPT JSONL row {index} input states must be lists")
                hotbar = raw.get("hotbar")
                if isinstance(hotbar, bool) or not isinstance(hotbar, int) or not 0 <= hotbar <= 8:
                    hotbar = None
                rows.append(
                    {
                        "tick": tick,
                        "milli": raw.get("milli"),
                        "keys": tuple(sorted({_canonical_vpt_key(value) for value in keys})),
                        "raw_keys": tuple(str(value) for value in keys),
                        "chars": keyboard.get("chars", ""),
                        "raw_buttons": tuple(buttons),
                        "x": mouse.get("x"),
                        "y": mouse.get("y"),
                        "locator": {
                            "line_number": index + 1,
                            "byte_offset": byte_offset - len(raw_line),
                            "frame_index": index,
                        },
                        "new_keys": tuple(str(value) for value in new_keys),
                        "buttons": tuple(sorted({_canonical_vpt_button(value) for value in buttons})),
                        "new_buttons": tuple(new_buttons),
                        "dx": _finite_number(mouse.get("dx"), field=f"rows[{index}].mouse.dx"),
                        "dy": _finite_number(mouse.get("dy"), field=f"rows[{index}].mouse.dy"),
                        "dwheel": _finite_number(mouse.get("dwheel", 0.0), field=f"rows[{index}].mouse.dwheel"),
                        "is_gui_open": bool(raw.get("isGuiOpen")),
                        "is_gui_inventory": bool(raw.get("isGuiInventory")),
                        "hotbar": hotbar,
                        "yaw": raw.get("yaw"),
                        "pitch": raw.get("pitch"),
                        "attack_stuck_repaired": False,
                    }
                )
        return rows

    def _apply_official_stuck_attack_repair(self) -> None:
        attack_is_stuck = self.rows[0]["new_buttons"] == (0,)
        for index, row in enumerate(self.rows):
            if index > 0 and attack_is_stuck and 0 in row["new_buttons"]:
                attack_is_stuck = False
            if attack_is_stuck and "left" in row["buttons"]:
                row["buttons"] = tuple(button for button in row["buttons"] if button != "left")
                row["attack_stuck_repaired"] = True

    def _validate_video_contract(self) -> int:
        stream = self.video_probe["stream"]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if width <= 0 or height <= 0:
            raise ValueError(f"VPT video has invalid encoded dimensions: {width}x{height}")
        self.video_width = width
        self.video_height = height
        frame_rate = Fraction(str(stream.get("avg_frame_rate") or "0/1"))
        if frame_rate != Fraction(ACTION_SAMPLE_RATE_HZ, 1):
            raise ValueError(f"VPT video must be {ACTION_SAMPLE_RATE_HZ} FPS, got {frame_rate}")
        frame_count = int(stream.get("nb_frames") or 0)
        expected_frame_count = len(self.rows) + 1
        if frame_count != expected_frame_count:
            raise ValueError(
                f"VPT video/action alignment requires N+1 frames: rows={len(self.rows)}, frames={frame_count}"
            )
        return frame_count

    def iter_anchors(self, config: SamplingConfig):
        first_index = max(
            math.ceil(config.start_time_ms / ACTION_STEP_MS - 1e-9),
            1,
        )
        stride_rows = int(ACTION_DURATION_MS / ACTION_STEP_MS)
        final_index = len(self.rows) - stride_rows  # The verified video has exactly N+1 frames.
        index = first_index
        emitted = 0
        while index <= final_index and (config.max_samples is None or emitted < config.max_samples):
            yield SampleAnchor(
                video_time_ms=index * ACTION_STEP_MS,
                source_index=index,
            )
            index += stride_rows
            emitted += 1

    def _frame_index(self, anchor: SampleAnchor, relative_time_ms: float) -> int | None:
        requested_ms = anchor.video_time_ms + relative_time_ms
        frame_index = round(requested_ms / ACTION_STEP_MS)
        if frame_index < 0 or frame_index >= self.video_frame_count:
            return None
        if abs(frame_index * ACTION_STEP_MS - requested_ms) > ACTION_STEP_MS / 2 + 1e-6:
            return None
        return frame_index

    def _planned_frame(
        self,
        anchor: SampleAnchor,
        relative_time_ms: float,
        output_root: Path,
        *,
        resize: FrameResizeSpec,
    ) -> MaterializedFrame | None:
        frame_index = self._frame_index(anchor, relative_time_ms)
        if frame_index is None:
            return None
        video_time_ms = frame_index * ACTION_STEP_MS
        path = output_root / "frames" / resize.cache_directory / f"frame-{frame_index:08d}.jpg"
        return MaterializedFrame(path=path, video_time_ms=video_time_ms)

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
            extract_video_frame(self.video_path, planned.video_time_ms, planned.path, resize=resize)
        return planned

    def _derived_hotbar_key(self, row_index: int) -> str | None:
        if row_index <= 0:
            return None
        row = self.rows[row_index]
        previous = self.rows[row_index - 1]
        if row["hotbar"] is None or previous["hotbar"] is None or row["hotbar"] == previous["hotbar"]:
            return None
        if any(
            self.rows[index]["dwheel"] for index in range(max(0, row_index - 1), min(len(self.rows), row_index + 2))
        ):
            return None
        hotbar_key = str(row["hotbar"] + 1)
        has_matching_key_onset = any(
            hotbar_key in set(self.rows[index]["keys"]) - set(self.rows[index - 1]["keys"])
            for index in range(max(1, row_index - 1), min(len(self.rows), row_index + 2))
        )
        return None if has_matching_key_onset else hotbar_key

    @property
    def source_native_onset_owner_policy(self) -> OnsetOwnerPolicy:
        return ANCHOR_INTERVAL_ONSET_OWNER

    def source_native_action_clock_ns(self, anchor: SampleAnchor) -> int:
        source_index = anchor.source_index
        if (
            isinstance(source_index, bool)
            or not isinstance(source_index, int)
            or not 0 <= source_index < len(self.rows)
        ):
            raise ValueError("VPT action clock requires a valid source row index")
        timestamp_ns = self._row_timestamp_ns(source_index)
        if round(float(anchor.video_time_ms) * 1_000_000) != timestamp_ns:
            raise ValueError("VPT anchor video time differs from its source row clock")
        return timestamp_ns

    def pointer_samples(self, anchor: SampleAnchor, interval: SourceActionInterval) -> list[dict]:
        if interval.anchor_ns != self.source_native_action_clock_ns(anchor) or interval.start_ns != interval.anchor_ns:
            raise ValueError("VPT source interval must start at its anchor clock")
        step_ns = self._row_timestamp_ns(1)
        start, a = divmod(interval.start_ns, step_ns)
        end, b = divmod(interval.end_ns, step_ns)
        if a or b:
            raise ValueError("VPT source interval must align to 50 ms action rows")
        if start <= 0 or end <= start or end > len(self.rows):
            raise ValueError("VPT source interval falls outside the paired action rows")
        samples = []
        for row in self.rows[start:end]:
            if row["is_gui_open"]:
                raise ValueError("GUI controls require operation-based preparation")
            sample = {}
            if row["dx"] or row["dy"]:
                sample["mouse_delta"] = {"dx": row["dx"], "dy": row["dy"], "space": "vpt_mouse_counts"}
            if row["dwheel"]:
                sample["scroll"] = {"dx": 0, "dy": -200 if row["dwheel"] > 0 else 200, "space": "player1_gym_wheel_px"}
            samples.append(sample)
        return samples

    @staticmethod
    def _row_timestamp_ns(row_index: int) -> int:
        return round(row_index * ACTION_STEP_MS * 1_000_000)

    def _keyboard_state(self, row_index: int, *, source_order: int) -> KeyboardState:
        keys_by_identity: dict[str, KeyboardKey] = {}
        for raw_key in self.rows[row_index]["raw_keys"]:
            source_key = str(raw_key).strip()
            identity = source_key.casefold()
            keys_by_identity[identity] = KeyboardKey(
                identity=identity,
                key=_canonical_vpt_key(source_key),
            )
        return KeyboardState(
            timestamp_ns=self._row_timestamp_ns(row_index),
            source_order=source_order,
            keys=tuple(sorted(keys_by_identity.values())),
            transition_exact=True,
        )

    def source_native_keyboard_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> KeyboardTimeline:
        """Return VPT's 20 Hz keyboard state timeline plus independent hotbar impulses."""

        if not math.isclose(horizon_ms, 200.0, abs_tol=1e-6):
            raise ValueError("VPT keyboard timeline requires a 200 ms action horizon")
        if len(anchors) != 50:
            raise ValueError("VPT keyboard timeline requires exactly 50 decision anchors")
        source_indices = [anchor.source_index for anchor in anchors]
        if any(index is None or not 0 <= index < len(self.rows) for index in source_indices):
            raise ValueError("VPT keyboard timeline anchors require valid source indices")
        window_starts_ns = tuple(self._row_timestamp_ns(int(index)) for index in source_indices)
        coverage_end_ns = window_starts_ns[-1] + round(horizon_ms * 1_000_000)
        recording_end_ns = self._row_timestamp_ns(len(self.rows))
        if recording_end_ns < coverage_end_ns:
            raise ValueError("VPT keyboard evidence does not cover the decision sequence")
        observed_end_ns = min(recording_end_ns, coverage_end_ns + _GESTURE_LOOKAROUND_NS)
        lookbehind_start_ns = window_starts_ns[0] - _GESTURE_LOOKAROUND_NS
        seed_index = max(0, math.floor(lookbehind_start_ns / (ACTION_STEP_MS * 1_000_000)))
        seed = self._keyboard_state(seed_index, source_order=seed_index * 2)

        checkpoints: list[KeyboardState] = []
        impulses: list[KeyboardImpulse] = []
        for row_index in range(seed_index + 1, len(self.rows)):
            timestamp_ns = self._row_timestamp_ns(row_index)
            if timestamp_ns > observed_end_ns:
                break
            checkpoints.append(self._keyboard_state(row_index, source_order=row_index * 2))
            hotbar_key = self._derived_hotbar_key(row_index)
            if hotbar_key is None:
                continue
            impulses.append(
                KeyboardImpulse(
                    timestamp_ns=timestamp_ns,
                    source_order=row_index * 2 + 1,
                    identity=f"hotbar:{hotbar_key}",
                    key=hotbar_key,
                )
            )

        return KeyboardTimeline(
            authority="vpt_keyboard_state_snapshots_20hz",
            evidence_kind="state_snapshots",
            window_starts_ns=window_starts_ns,
            seed=seed,
            checkpoints=tuple(checkpoints),
            edges=(),
            observed_end_ns=observed_end_ns,
            impulses=tuple(impulses),
            maximum_sample_gap_ns=50_000_000,
        )

    def source_native_mouse_button_timeline(
        self,
        anchors: tuple[SampleAnchor, ...],
        horizon_ms: float,
    ) -> QuantizedMouseButtonTimeline:
        """Return the repaired 20 Hz held-button state across the full trajectory context."""

        if not math.isclose(horizon_ms, 200.0, abs_tol=1e-6):
            raise ValueError("VPT mouse timeline requires a 200 ms action horizon")
        if len(anchors) != 50:
            raise ValueError("VPT mouse timeline requires exactly 50 decision anchors")
        source_indices = [anchor.source_index for anchor in anchors]
        if any(index is None or not 0 <= index < len(self.rows) for index in source_indices):
            raise ValueError("VPT mouse timeline anchors require valid source indices")
        window_starts_ns = tuple(self._row_timestamp_ns(int(index)) for index in source_indices)
        coverage_end_ns = window_starts_ns[-1] + round(horizon_ms * 1_000_000)
        recording_end_ns = self._row_timestamp_ns(len(self.rows))
        if recording_end_ns < coverage_end_ns:
            raise ValueError("VPT mouse evidence does not cover the decision sequence")
        observed_end_ns = min(recording_end_ns, coverage_end_ns + _GESTURE_LOOKAROUND_NS)
        seed_index = max(
            0,
            math.floor((window_starts_ns[0] - _GESTURE_LOOKAROUND_NS) / (ACTION_STEP_MS * 1_000_000)),
        )

        for row_index in range(seed_index, len(self.rows)):
            if self._row_timestamp_ns(row_index) > observed_end_ns:
                break
            row = self.rows[row_index]
            witness = tuple(_canonical_vpt_button(value) for value in row["new_buttons"])
            if len(witness) != len(set(witness)) or set(witness) - set(STANDARD_MOUSE_BUTTONS):
                raise ValueError("VPT newButtons contains invalid or repeated button identities")
            if not witness or (row_index == 0 and row["new_buttons"] == (0,)):
                continue
            previous_buttons = set(self.rows[row_index - 1]["buttons"]) if row_index else set()
            repaired_onsets = set(row["buttons"]) - previous_buttons
            if not set(witness).issubset(repaired_onsets):
                raise ValueError("VPT newButtons witness disagrees with repaired mouse button state")

        def state(row_index: int) -> MouseButtonState:
            return MouseButtonState(
                timestamp_ns=self._row_timestamp_ns(row_index),
                source_order=row_index,
                buttons=frozenset(self.rows[row_index]["buttons"]),
            )

        checkpoints = tuple(
            state(row_index)
            for row_index in range(seed_index + 1, len(self.rows))
            if self._row_timestamp_ns(row_index) <= observed_end_ns
        )
        return QuantizedMouseButtonTimeline(
            authority="vpt_repaired_mouse_button_state_snapshots_20hz",
            window_starts_ns=window_starts_ns,
            seed=state(seed_index),
            checkpoints=checkpoints,
            observed_end_ns=observed_end_ns,
            maximum_sample_gap_ns=50_000_000,
        )

    def observation_geometry(self, anchor: SampleAnchor) -> dict[str, Any]:
        del anchor
        return {
            "width_px": self.video_width,
            "height_px": self.video_height,
            "source": "ffprobe_paired_vpt_video",
        }


def cursor_plane_conflict(exits: tuple, end_ns: int) -> dict | None:
    """Detect repeated GUI-exit recentres contradicting the nominal 1280x720 plane.

    A single exit can include mouse movement. Require the candidate's exit and
    two nearby exits to agree within eight source pixels, away from the nominal
    centre by more than sixteen pixels. This is a contradiction check, not a
    calibration: do not infer another viewport size or rescale from these points.
    Visual coordinate correspondence is still required when no conflict is found.
    """
    index = bisect_left(exits, (end_ns // _GUI_STEP_NS,))
    if index == len(exits):
        return None
    frame, x, y = exits[index]
    if max(abs(x - 640), abs(y - 360)) <= 16:
        return None
    neighbours = exits[max(0, index - 2) : index + 3]
    agreeing = [row for row in neighbours if max(abs(row[1] - x), abs(row[2] - y)) <= 8]
    if len(agreeing) < 3:
        return None
    return {
        "reason": "VPT GUI recentres contradict the nominal cursor plane",
        "nominal_geometry": [1280, 720],
        "candidate_exit_frame": frame,
        "exit_positions": agreeing,
    }


def vpt_events(rows: list[dict]) -> list[Event]:
    events = []
    previous = None
    for index, row in enumerate(rows):
        now, locator = index * _GUI_STEP_NS, row["locator"]

        def add(kind, **value):
            events.append(Event(now, kind, value, locator))

        if not row["gui"]:
            if previous is not None:
                add("boundary", reason="GUI closed")
            previous = None
            continue
        try:
            point = position(row["x"], row["y"], 1280, 720)
        except (ValueError, TypeError):
            add("boundary", reason="recorded cursor unavailable")
            previous = None
            continue
        if previous is None:
            add("boundary", reason="GUI starts")
            if row["buttons"] or row["keys"] - MODIFIERS:
                continue  # Cannot invent the press preceding this GUI interval.
            # A GUI-entry cursor snapshot is state, not the start of a targeting
            # movement. Its corresponding video frame may still show the opener.
            add("cursor_state", position=point)
            add("modifier_state", keys=sorted(row["keys"] & MODIFIERS))
            previous = row
            continue
        old_buttons, old_keys = previous["buttons"], previous["keys"]
        for key in sorted((old_keys ^ row["keys"]) & MODIFIERS):
            add("modifier", key=key, down=key in row["keys"])
        new_keys = row["keys"] - old_keys - MODIFIERS
        new_buttons = row["buttons"] - old_buttons
        if (
            row["buttons"] - _BUTTON_NAMES.keys()
            or len(row["buttons"]) > 1
            or row["keys"] - MODIFIERS
            and (row["buttons"] or old_buttons or row["wheel"])
            or row["wheel"]
            and (row["buttons"] or old_buttons)
            or any(button in old_buttons and button in row["buttons"] for button in row["new_buttons"])
            or row["chars"]
            and not (new_keys or row["keys"] - MODIFIERS)
        ):
            add("boundary", reason="overlapping or unresolved raw GUI input")
            previous = row
            continue
        # Release at the first non-held row, before its newly observed movement.
        for button in sorted(old_buttons - row["buttons"]):
            add("release", button=_BUTTON_NAMES[button])
        add("move", position=point)
        if new_buttons or row["wheel"] or new_keys:
            add("modifier_state", keys=sorted(row["keys"] & MODIFIERS))
        for button in sorted(new_buttons):
            add("press", button=_BUTTON_NAMES[button], position=point)
        if row["wheel"]:
            add("scroll", dx=0, dy=row["wheel"], unit="vpt_dwheel", end_ns=now + _GUI_STEP_NS)
        if new_keys:
            # Keep raw key identity rather than guessing typed text from a keyboard layout.
            end = index + 1
            while end < len(rows) and rows[end]["gui"] and new_keys & rows[end]["keys"]:
                end += 1
            if end >= len(rows) or not rows[end]["gui"]:
                add("boundary", reason="key gesture crosses GUI boundary")
            else:
                add("key_press", keys=sorted(new_keys), end_ns=end * _GUI_STEP_NS)
        previous = row
    events.append(Event(len(rows) * _GUI_STEP_NS, "boundary", {"reason": "recording ends"}, {}))
    return events


__all__ = [
    "ACTION_SAMPLE_RATE_HZ",
    "ACTION_STEP_MS",
    "DATASET_ID",
    "MOUSE_DEGREES_PER_COUNT",
    "SOURCE_URL",
    "VPTContractorAdapter",
]
