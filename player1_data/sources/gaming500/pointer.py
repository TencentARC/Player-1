"""Gaming500 screen geometry, pointer evidence and captured-camera detection."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

POINTER_LOCK_CENTER = 500
POINTER_LOCK_CENTER_DEADZONE_MAX_EXCLUSIVE = 10
POINTER_LOCK_MIN_MOTION_EVENTS = 20
POINTER_LOCK_MIN_SPAN_MS = 500.0
POINTER_LOCK_MAX_INTER_EVENT_GAP_MS = 500.0
POINTER_MODE_EVIDENCE_WINDOW_MS = 1_000.0
POINTER_LOCK_MIN_CENTER_FRACTION = 0.30
POINTER_LOCK_MIN_RECENTER_RETURNS = 2
POINTER_LOCK_AMBIGUOUS_CENTER_FRACTION = 0.10


@dataclass(frozen=True)
class ScreenGeometry:
    index: int
    origin_x: float
    origin_y: float
    width: float
    height: float

    @classmethod
    def from_source(cls, payload: dict[str, Any]) -> ScreenGeometry | None:
        width = _number(payload.get("width"))
        height = _number(payload.get("height"))
        if width is None or height is None or width <= 0 or height <= 0:
            return None
        return cls(
            index=int(payload.get("index") or 0),
            origin_x=_number(payload.get("originX")) or 0.0,
            origin_y=_number(payload.get("originY")) or 0.0,
            width=width,
            height=height,
        )

    def normalize_absolute(self, x: float, y: float) -> tuple[float, float]:
        return (
            1000.0 * (x - self.origin_x) / self.width,
            1000.0 * (y - self.origin_y) / self.height,
        )

    def contains(self, x: float, y: float) -> bool:
        return self.origin_x <= x <= self.origin_x + self.width and self.origin_y <= y <= self.origin_y + self.height

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "width": self.width,
            "height": self.height,
        }


_MOTION_EVENT_TYPES = frozenset({"drag", "mouse_move"})


def _is_centered(x: int, y: int) -> bool:
    return max(abs(x - POINTER_LOCK_CENTER), abs(y - POINTER_LOCK_CENTER)) < (
        POINTER_LOCK_CENTER_DEADZONE_MAX_EXCLUSIVE
    )


@dataclass(frozen=True)
class _PointerObservation:
    event_type: str
    source_time_ms: float
    wire_x: int
    wire_y: int
    geometry_key: tuple[int, float, float, float, float]
    segment_id: int | None

    @property
    def is_centered(self) -> bool:
        return _is_centered(self.wire_x, self.wire_y)


@dataclass(frozen=True)
class _LockedInterval:
    start_ms: float
    end_ms: float
    geometry_key: tuple[int, float, float, float, float]


@dataclass(frozen=True)
class GamingPointerModeEvidence:
    """Compact pointer-mode intervals derived once from a session timeline."""

    locked_intervals: tuple[_LockedInterval, ...]
    ambiguous_intervals: tuple[_LockedInterval, ...]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _session_observations(pointer_timeline: Sequence[Mapping[str, Any]]) -> list[_PointerObservation]:
    observations: list[_PointerObservation] = []
    for point in pointer_timeline:
        if point.get("event_type") not in _MOTION_EVENT_TYPES or point.get("mapping_status") != "exact":
            continue
        target = point.get("target")
        geometry = point.get("screen_geometry")
        source_time_ms = _number(point.get("video_t_ms"))
        if not isinstance(target, Mapping) or not isinstance(geometry, Mapping) or source_time_ms is None:
            continue
        wire_x = target.get("x")
        wire_y = target.get("y")
        screen_index = point.get("screen_index")
        origin_x = _number(geometry.get("origin_x"))
        origin_y = _number(geometry.get("origin_y"))
        width = _number(geometry.get("width"))
        height = _number(geometry.get("height"))
        segment_id = point.get("segment_id")
        if (
            isinstance(wire_x, bool)
            or not isinstance(wire_x, int)
            or isinstance(wire_y, bool)
            or not isinstance(wire_y, int)
            or isinstance(screen_index, bool)
            or not isinstance(screen_index, int)
            or origin_x is None
            or origin_y is None
            or width is None
            or height is None
            or isinstance(segment_id, bool)
            or not isinstance(segment_id, int)
        ):
            continue
        observations.append(
            _PointerObservation(
                event_type=str(point["event_type"]),
                source_time_ms=source_time_ms,
                wire_x=wire_x,
                wire_y=wire_y,
                geometry_key=(screen_index, origin_x, origin_y, width, height),
                segment_id=segment_id,
            )
        )
    observations.sort(key=lambda item: item.source_time_ms)
    return observations


def _pointer_mode_intervals(
    observations: Sequence[_PointerObservation],
) -> tuple[tuple[_LockedInterval, ...], tuple[_LockedInterval, ...]]:
    """Classify local session intervals without splitting on cursor excursions."""

    locked: list[_LockedInterval] = []
    ambiguous: list[_LockedInterval] = []
    burst: list[_PointerObservation] = []

    def finish_burst() -> None:
        nonlocal burst
        left = 0
        for right, current in enumerate(burst):
            while current.source_time_ms - burst[left].source_time_ms > POINTER_MODE_EVIDENCE_WINDOW_MS:
                left += 1
            evidence = burst[left : right + 1]
            if (
                len(evidence) < POINTER_LOCK_MIN_MOTION_EVENTS
                or current.source_time_ms - evidence[0].source_time_ms < POINTER_LOCK_MIN_SPAN_MS
            ):
                continue
            center_fraction = sum(item.is_centered for item in evidence) / len(evidence)
            returns = sum(not previous.is_centered and current.is_centered for previous, current in pairwise(evidence))
            interval = _LockedInterval(
                start_ms=evidence[0].source_time_ms,
                end_ms=current.source_time_ms,
                geometry_key=evidence[0].geometry_key,
            )
            if center_fraction >= POINTER_LOCK_MIN_CENTER_FRACTION and (
                returns >= POINTER_LOCK_MIN_RECENTER_RETURNS or center_fraction >= 0.80
            ):
                locked.append(interval)
            elif center_fraction >= POINTER_LOCK_AMBIGUOUS_CENTER_FRACTION and returns:
                ambiguous.append(interval)
        burst = []

    for observation in observations:
        if observation.event_type not in _MOTION_EVENT_TYPES:
            continue
        if burst and (
            observation.geometry_key != burst[-1].geometry_key
            or observation.segment_id != burst[-1].segment_id
            or observation.source_time_ms - burst[-1].source_time_ms > POINTER_LOCK_MAX_INTER_EVENT_GAP_MS
        ):
            finish_burst()
        burst.append(observation)
    finish_burst()
    return _merge_intervals(locked), _merge_intervals(ambiguous)


def _merge_intervals(intervals: Sequence[_LockedInterval]) -> tuple[_LockedInterval, ...]:
    merged: list[_LockedInterval] = []
    for interval in intervals:
        if (
            merged
            and merged[-1].geometry_key == interval.geometry_key
            and interval.start_ms <= merged[-1].end_ms + POINTER_LOCK_MAX_INTER_EVENT_GAP_MS
        ):
            previous = merged[-1]
            merged[-1] = _LockedInterval(
                previous.start_ms,
                max(previous.end_ms, interval.end_ms),
                previous.geometry_key,
            )
        else:
            merged.append(interval)
    return tuple(merged)


def classify_gaming_pointer_timeline(
    pointer_timeline: Sequence[Mapping[str, Any]],
) -> GamingPointerModeEvidence:
    """Compile one raw session timeline into reusable pointer-mode evidence."""

    locked, ambiguous = _pointer_mode_intervals(_session_observations(pointer_timeline))
    return GamingPointerModeEvidence(locked_intervals=locked, ambiguous_intervals=ambiguous)


@dataclass(frozen=True)
class PointerContext:
    screen_index: int
    app_key: str | None


class PointerDecoder:
    """Decode source geometry and points without inventing relative camera actions."""

    def __init__(self):
        self.screens: dict[int, ScreenGeometry] = {}
        self.active_app_key = None
        self.active_app = None
        self.context = None
        self.segment_id = 0

    def _reset_context(self):
        if self.context is not None:
            self.segment_id += 1
        self.context = None

    def _update_screen_config(self, event):
        values = event.get("screens")
        if isinstance(values, str):
            try:
                values = json.loads(values)
            except json.JSONDecodeError:
                return
        if not isinstance(values, list):
            return
        screens = {}
        for value in values:
            if isinstance(value, dict):
                screen = ScreenGeometry.from_source(value)
                if screen is not None:
                    screens[screen.index] = screen
        if screens:
            self.screens = screens
            self._reset_context()

    def _update_active_app(self, event):
        app_key = str(event.get("bundleId") or event.get("name") or "") or None
        if (self.context is not None and app_key != self.context.app_key) or (
            self.active_app_key is not None and app_key != self.active_app_key
        ):
            self._reset_context()
        self.active_app_key = app_key
        self.active_app = event

    def _screen_for_event(self, event, x, y):
        index = event.get("screen")
        if isinstance(index, int):
            return (self.screens[index], None) if index in self.screens else (None, "event_screen_unknown")
        screen = next((s for s in self.screens.values() if s.contains(x, y)), None)
        if screen is not None:
            return screen, None
        if self.context is not None and self.context.screen_index in self.screens:
            return self.screens[self.context.screen_index], "event_coordinates_outside_known_screens"
        if self.screens:
            return self.screens[min(self.screens)], "event_coordinates_outside_known_screens"
        return None, "screen_config_missing"

    def process_frame(self, frame):
        points, failures = [], []
        frame_time = float(frame.get("video_t_ms", 0.0))
        events = frame.get("events") if isinstance(frame.get("events"), list) else []
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            kind = str(event.get("type") or "")
            if kind == "screen_config":
                self._update_screen_config(event)
                continue
            if kind == "active_app":
                self._update_active_app(event)
                continue
            if kind not in {"click", "drag", "mouse_move"}:
                continue
            stamp = event.get("video_t_ms")
            stamp = float(stamp) if isinstance(stamp, (int, float)) else frame_time
            x, y = _number(event.get("x")), _number(event.get("y"))
            screen, reason = (
                self._screen_for_event(event, x, y)
                if x is not None and y is not None
                else (None, "missing_pointer_coordinates")
            )
            if screen is None:
                failures.append(
                    {
                        "event_index": index,
                        "event_type": kind,
                        "video_t_ms": stamp,
                        "mapping_status": "unavailable",
                        "reason": reason,
                    }
                )
                if reason != "missing_pointer_coordinates":
                    self._reset_context()
                continue
            app_key = str(event.get("bundleId") or event.get("appName") or "") or self.active_app_key
            if self.context is not None and (
                self.context.screen_index != screen.index or self.context.app_key != app_key
            ):
                self._reset_context()
            if reason is not None:
                failures.append(
                    {
                        "event_index": index,
                        "event_type": kind,
                        "video_t_ms": stamp,
                        "mapping_status": "unavailable",
                        "reason": reason,
                    }
                )
            in_bounds = screen.contains(x, y)
            nx, ny = screen.normalize_absolute(x, y)
            points.append(
                {
                    "event_index": index,
                    "event_type": kind,
                    "video_t_ms": stamp,
                    "segment_id": self.segment_id,
                    "screen_index": screen.index,
                    "source": {"x": x, "y": y},
                    "target": {"x": round(nx), "y": round(ny)} if in_bounds and reason is None else None,
                    "in_bounds": in_bounds,
                    "mapping_status": "exact" if in_bounds and reason is None else "unavailable",
                    "mapping_reason": reason
                    if reason is not None
                    else (None if in_bounds else "pointer_coordinates_out_of_bounds"),
                    "screen_geometry": screen.to_dict(),
                    **({"isDown": event["isDown"]} if "isDown" in event else {}),
                }
            )
            if reason is None:
                self.context = PointerContext(screen.index, app_key)
            else:
                self._reset_context()
        return {
            "screens": [s.to_dict() for s in sorted(self.screens.values(), key=lambda s: s.index)],
            "active_app": self.active_app,
            "points": points,
            "failures": failures,
        }
