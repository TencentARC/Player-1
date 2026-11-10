"""Recorded GUI operations, causal observations and complete 25–50-turn trajectories."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from math import floor, isfinite
from pathlib import Path

from player1_data.files import file_digest
from player1_data.sources.common import (
    FrameResizeSpec,
    extract_video_frame,
    probe_immutable_source_video_frame_times_ms,
)
from player1_data.standardize.actions import frame_action

MIN_STEPS = 25
MAX_STEPS = 50
MAX_IDLE_NS = 15_000_000_000
MODIFIERS = frozenset({"shift", "control", "alt", "meta"})
SCROLL_BURST_NS = 500_000_000


@dataclass(frozen=True)
class Event:
    time_ns: int
    kind: str
    value: dict
    locator: dict


def position(x: float, y: float, width: float, height: float) -> dict:
    if not all(isfinite(v) for v in (x, y, width, height)) or min(width, height) <= 0:
        raise ValueError("invalid recorded cursor geometry")
    if not 0 <= x <= width or not 0 <= y <= height:
        raise ValueError("recorded cursor outside viewport")
    return {"mode": "absolute", "x": floor(x / width * 1000 + 0.5), "y": floor(y / height * 1000 + 0.5)}


def _typing_stroke(action: dict) -> bool:
    return (
        action["kind"] == "key_press"
        and set(action["modifiers"]) <= {"shift"}
        and all(len(key) == 1 or key in {"space", "backspace"} for key in action["keys"])
    )


def coalesce_scrolls(sequence: list[dict]) -> list[dict]:
    """Coalesce a same-direction wheel burst while retaining its source segments."""
    result = []
    for original in sequence:
        operation = deepcopy(original)
        previous = result[-1] if result else None
        action = operation["action"]
        if not (
            previous
            and previous["action"]["kind"] == action["kind"] == "scroll"
            and 0 <= operation["trigger_ns"] - previous["end_ns"] <= SCROLL_BURST_NS
            and previous["action"]["modifiers"] == action["modifiers"]
            and previous["action"]["unit"] == action["unit"]
            and all(previous["action"][axis] * action[axis] >= 0 for axis in ("dx", "dy"))
        ):
            result.append(operation)
            continue

        def segments(step):
            value = step["action"]
            return value.get("segments", [{**value, "trigger_ns": step["trigger_ns"], "end_ns": step["end_ns"]}])

        previous["action"]["segments"] = [*segments(previous), *segments(operation)]
        for axis in ("dx", "dy"):
            previous["action"][axis] += action[axis]
        previous["end_ns"] = operation["end_ns"]
        previous["source_events"].extend(operation["source_events"])
    return result


def operations(events: list[Event]) -> list[list[dict]]:
    """Group exact input edges; an unrepresentable gesture breaks continuity.

    Motion leading to a click belongs to that click. Motion while pressed is a
    drag with its recorded path. Motion after release belongs to the next action.
    Standalone motion/idle is context, never an invented operation.
    """
    groups, current = [], []
    pressed = None
    key_pressed = None
    held_keys: set[str] = set()
    modifiers: set[str] = set()
    movement_start = None
    cursor = None
    last_time = -1

    def boundary():
        nonlocal current, pressed, key_pressed, movement_start
        if current:
            groups.append(coalesce_scrolls(current))
        current, pressed, key_pressed, movement_start = [], None, None, None

    def emit(action, start, trigger, end, evidence):
        nonlocal movement_start
        if current and start - current[-1]["end_ns"] > MAX_IDLE_NS:
            boundary()
        # A continuous text-entry burst is one operation. Preserve physical key
        # strokes (including durations/modifiers), not guessed committed text.
        previous = current[-1] if current else None
        if _typing_stroke(action) and previous:
            previous_action = previous["action"]
            if previous_action["kind"] == "key_sequence" or _typing_stroke(previous_action):
                if 0 <= trigger - previous["end_ns"] <= 1_000_000_000:
                    if previous_action["kind"] == "key_press":
                        previous["action"] = {
                            "kind": "key_sequence",
                            "strokes": [
                                {
                                    **previous_action,
                                    "offset_ms": 0,
                                    "duration_ms": (previous["end_ns"] - previous["trigger_ns"]) / 1e6,
                                }
                            ],
                        }
                    previous["action"]["strokes"].append(
                        {
                            **action,
                            "offset_ms": (trigger - previous["trigger_ns"]) / 1e6,
                            "duration_ms": (end - trigger) / 1e6,
                        }
                    )
                    previous["end_ns"] = end
                    previous["source_events"].extend(evidence)
                    movement_start = None
                    return
        current.append(dict(start_ns=start, trigger_ns=trigger, end_ns=end, action=action, source_events=evidence))
        movement_start = None

    for event in events:
        if event.time_ns < last_time:
            raise ValueError("GUI events must be chronological")
        last_time = event.time_ns
        value, now = event.value, event.time_ns
        if event.kind == "boundary":
            boundary()
            modifiers.clear()
            cursor = None
        elif event.kind == "keyboard_state":
            state = set(value["keys"])
            if state != held_keys:
                boundary()  # A snapshot cannot supply a missing press or release.
                held_keys = state
        elif event.kind == "key_down":
            key = value["key"]
            if key in held_keys:
                if key_pressed and key_pressed["key"] == key:
                    key_pressed["repeats"].append({"time_ns": now, "source_event": event.locator})
                continue
            if held_keys or pressed:
                boundary()
            else:
                key_pressed = dict(key=key, start=now, modifiers=sorted(modifiers), evidence=event.locator, repeats=[])
            held_keys.add(key)
        elif event.kind == "key_up":
            key = value["key"]
            held_keys.discard(key)
            gesture = key_pressed
            key_pressed = None
            if gesture is None or gesture["key"] != key or now <= gesture["start"]:
                boundary()
                continue
            action = {"kind": "key_press", "keys": [key], "modifiers": gesture["modifiers"]}
            if gesture["repeats"]:
                action["repeat_events"] = gesture["repeats"]
            emit(action, gesture["start"], gesture["start"], now, [gesture["evidence"], event.locator])
        elif event.kind == "modifier_state":
            state = set(value["keys"])
            if not state <= MODIFIERS:
                raise ValueError("GUI modifier state contains non-modifier keys")
            if (pressed or key_pressed) and state != modifiers:
                boundary()
            modifiers = state
        elif event.kind == "modifier":
            if pressed or key_pressed:
                boundary()  # Changing modifiers during a gesture needs a richer execution contract.
            if value["down"]:
                modifiers.add(value["key"])
            else:
                modifiers.discard(value["key"])
        elif event.kind == "cursor_state":
            cursor = value["position"]
            movement_start = None
        elif event.kind == "move":
            point = value["position"]
            if point != cursor:
                movement_start = now if movement_start is None else movement_start
                if pressed:
                    pressed["path"].append({"time_ns": now, **point})
            cursor = point
        elif event.kind == "press":
            if pressed or held_keys:
                boundary()
                continue
            cursor = value["position"]
            pressed = dict(
                start=movement_start if movement_start is not None else now,
                trigger=now,
                point=cursor,
                button=value["button"],
                modifiers=sorted(modifiers),
                path=[{"time_ns": now, **cursor}],
                evidence=[event.locator],
            )
        elif event.kind == "release":
            if not pressed or pressed["button"] != value["button"]:
                boundary()
                continue
            gesture = pressed
            pressed = None
            if now <= gesture["trigger"]:
                boundary()
                continue
            path = gesture["path"]
            if value.get("position") and value["position"] != {k: path[-1][k] for k in ("mode", "x", "y")}:
                path.append({"time_ns": now, **value["position"]})
            duration = (now - gesture["trigger"]) / 1e6
            action = dict(
                kind="drag" if len(path) > 1 else "click" if duration < 300 else "mouse_hold",
                button=gesture["button"],
                position=gesture["point"],
                duration_ms=duration,
                modifiers=gesture["modifiers"],
            )
            if action["kind"] == "drag":
                action["path"] = path
            emit(action, gesture["start"], gesture["trigger"], now, [*gesture["evidence"], event.locator])
        elif event.kind in {"scroll", "key_press"}:
            if pressed or held_keys:
                boundary()
                continue
            action = {"kind": event.kind, **value, "modifiers": sorted(modifiers)}
            start = movement_start if event.kind == "scroll" and movement_start is not None else now
            if event.kind == "scroll" and cursor:
                action["position"] = cursor
            end = value.get("end_ns", now + 1)
            action.pop("end_ns", None)
            emit(action, start, now, end, [event.locator])
        else:
            raise ValueError(f"unknown GUI input event: {event.kind}")
    boundary()
    return groups


def frame_bound_groups(groups: list[list[dict]], frame_times: list[int]) -> list[list[dict]]:
    """Bind pre-action observations and post-action results to actual source frames."""
    result = []
    for group in groups:
        current = []
        for index, operation in enumerate(group):
            pre = bisect_right(frame_times, operation["start_ns"]) - 1
            if current and pre >= 0 and frame_times[pre] < current[-1]["result_ns"]:
                # A human can start moving before the first post-click frame.
                # Observe the completed previous operation, then target the next
                # recorded click. Never require replay of already observed motion.
                pre = bisect_left(frame_times, current[-1]["result_ns"])
            post = bisect_left(frame_times, operation["end_ns"])
            next_start = group[index + 1]["trigger_ns"] if index + 1 < len(group) else float("inf")
            valid = (
                pre >= 0
                and pre < len(frame_times)
                and frame_times[pre] <= operation["trigger_ns"]
                and post < len(frame_times)
                and frame_times[post] <= next_start
                and (not current or frame_times[pre] >= current[-1]["result_ns"])
                and operation["start_ns"] - frame_times[max(pre, 0)] <= 100_000_000
                and (post >= len(frame_times) or frame_times[post] - operation["end_ns"] <= 100_000_000)
            )
            if not valid:
                if current:
                    result.append(current)
                current = []
                continue
            current.append(
                {
                    **operation,
                    "movement_onset_ns": operation["start_ns"],
                    "start_ns": max(operation["start_ns"], frame_times[pre]),
                    "observation_ns": frame_times[pre],
                    "result_ns": frame_times[post],
                }
            )
        if current:
            result.append(current)
    return result


def _regions(groups: list[list[dict]], regions: list[tuple[int, int]], excluded: list[tuple[int, int]]):
    """Partition complete operations within explicit regions into 25–50 ops.

    Baseline exclusions split a group; they are not removed then stitched over.
    An operation crossing a region boundary is excluded, never clipped.
    """
    for group in groups:
        if not any(group[0]["observation_ns"] <= end and group[-1]["result_ns"] >= start for start, end in regions):
            continue
        allowed, chunks = [], []
        for operation in group:
            if not any(
                start <= operation["observation_ns"] and operation["result_ns"] <= end for start, end in regions
            ) or any(operation["observation_ns"] < end and operation["result_ns"] > start for start, end in excluded):
                if allowed:
                    chunks.append(allowed)
                allowed = []
            else:
                allowed.append(operation)
        if allowed:
            chunks.append(allowed)
        for chunk in chunks:
            # Check the entire interval too: a baseline interval can lie in an idle gap.
            start = 0
            for i in range(1, len(chunk) + 1):
                cut = (
                    i == len(chunk)
                    or any(chunk[i - 1]["result_ns"] <= left < chunk[i]["observation_ns"] for left, _ in excluded)
                    or not any(
                        left <= chunk[i - 1]["observation_ns"] and chunk[i]["result_ns"] <= right
                        for left, right in regions
                    )
                )
                if cut:
                    continuous = chunk[start:i]
                    yield continuous
                    start = i


TOLERANCE_NS = 50_000_000
ROUNDING_NS = 1000


def _target_position(value):
    return {key: value[key] for key in ("mode", "x", "y")}


def time_offset(base, milliseconds):
    return base + int(Decimal(str(milliseconds)) * 1_000_000)


def expand_operation(step):
    """Use drag endpoints, explicit mouse-up, and one direction step per scroll gesture."""
    action = step["action"]
    kind = action["kind"]
    modifiers = action.get("modifiers", [])
    children = []

    def emit(trigger, end, args, role, mods=modifiers):
        args = dict(args)
        if mods:
            args["key_hold"] = mods
        frame, canonical = frame_action(args)
        children.append(
            {"trigger_ns": trigger, "source_end_ns": end, "role": role, "action": frame, "canonical_action": canonical}
        )

    if kind == "click":
        emit(
            step["trigger_ns"],
            step["end_ns"],
            dict(mouse_move=_target_position(action["position"]), mouse_click=action["button"]),
            "click",
        )
    elif kind in {"drag", "mouse_hold"}:
        points = [dict(time_ns=step["trigger_ns"], **_target_position(action["position"]))]
        if kind == "drag":
            points.append(dict(action["path"][-1]))
        for i, point in enumerate(points):
            emit(
                point["time_ns"],
                point["time_ns"],
                dict(mouse_move=_target_position(point), mouse_hold=action["button"]),
                "press" if i == 0 else "drag_move",
            )
        emit(step["end_ns"], step["end_ns"], {}, "release")
    elif kind == "scroll":
        segments = action.get("segments") or [dict(action, trigger_ns=step["trigger_ns"], end_ns=step["end_ns"])]
        directions = set()
        for segment in segments:
            dx, dy = segment.get("dx", 0), segment.get("dy", 0)
            if dx:
                raise ValueError("horizontal_scroll_unsupported")
            if dy:
                directions.add("down" if dy > 0 else "up")
            if segment.get("modifiers", modifiers) != modifiers:
                raise ValueError("scroll_modifiers_changed")
        # Source intake groups a same-direction gesture. Its magnitude and cursor
        # jitter are deliberately collapsed, using the first recorded target and
        # the original pre-operation observation. Keep the whole source interval.
        target = segments[0].get("position", action.get("position"))
        args = {}
        if target:
            args["mouse_move"] = _target_position(target)
        else:
            raise ValueError("scroll_position_missing")
        if len(directions) == 1:
            args["mouse_scroll"] = next(iter(directions))
        else:
            raise ValueError("scroll_direction_changed" if directions else "vertical_scroll_absent")
        emit(step["trigger_ns"], step["end_ns"], args, "scroll_direction_once")
    elif kind in {"key_press", "key_sequence"}:
        for stroke in action.get("strokes", [action]):
            start = time_offset(step["trigger_ns"], stroke.get("offset_ms", 0))
            end = time_offset(start, stroke["duration_ms"]) if "duration_ms" in stroke else step["end_ns"]
            repeats = stroke.get("repeat_events", [])
            if repeats:
                raise ValueError("keyboard_repeat_mapping_unresolved")
            emit(start, end, dict(key_tap=stroke["keys"]), "key_press", mods=stroke.get("modifiers", modifiers))
    else:
        raise ValueError("unknown_operation:" + kind)
    return children


def frame_bounds(trigger, previous_end):
    # An observation must follow the preceding input, and not cross the current trigger.
    # Same-clock events cannot manufacture an intermediate visible state.
    lower = trigger - TOLERANCE_NS
    if previous_end is not None:
        lower = max(lower, previous_end + ROUNDING_NS + 1)
    return lower, trigger + ROUNDING_NS


def candidate_frame(points, lower, upper):
    if lower > upper:
        return None
    index = bisect_right(points, upper) - 1
    return points[index] if index >= 0 and points[index] >= lower else None


def prepared_parent_frame(frame_ns, trigger, previous_end):
    """Retain the accepted operation's original pre-motion observation, even when older than 50 ms."""
    return frame_ns <= trigger + ROUNDING_NS and (previous_end is None or frame_ns >= previous_end - ROUNDING_NS)


def _turn_batches(operations):
    """Partition the longest usable prefix, keeping every operation indivisible."""
    parents = {0: None}
    for end in range(1, len(operations) + 1):
        count = 0
        for start in range(end - 1, -1, -1):
            count += len(operations[start])
            if count > MAX_STEPS:
                break
            if count >= MIN_STEPS and start in parents:
                parents[end] = start
                break
    end = max(parents)
    batches = []
    while end:
        start = parents[end]
        batches.append([child for operation in operations[start:end] for child in operation])
        end = start
    yield from reversed(batches)


def trajectories(groups, regions, excluded, frame_times):
    for continuous in _regions(groups, regions, excluded):
        expanded, previous_end = [], None
        for operation in continuous:
            children = expand_operation(operation)
            if len(children) > MAX_STEPS:
                raise ValueError("One complete GUI operation exceeds 50 turns")
            for index, child in enumerate(children):
                timestamp = operation["observation_ns"]
                if index or not prepared_parent_frame(timestamp, child["trigger_ns"], previous_end):
                    lower, upper = frame_bounds(child["trigger_ns"], previous_end)
                    timestamp = candidate_frame(frame_times, lower, min(upper, child["trigger_ns"]))
                if timestamp is None or timestamp > child["trigger_ns"]:
                    raise ValueError("GUI child has no real causal observation")
                child["observation_ns"] = timestamp
                previous_end = child["source_end_ns"]
            expanded.append(children)
        yield from _turn_batches(expanded)


def gui_trajectories(adapter, record):
    points = [round(ms * 1e6) for ms in probe_immutable_source_video_frame_times_ms(adapter.video_path)]
    if not points:
        raise ValueError("GUI recording has no video frames")
    read_events = getattr(adapter, "gui_events", None)
    if read_events is None:
        raise ValueError(f"Operation-based GUI input is not implemented for {record['source']}")
    groups = frame_bound_groups(operations(read_events()), points)
    regions = [tuple(p) for p in record.get("regions_ns", [[points[0], points[-1]]])]
    yield from trajectories(groups, regions, [tuple(p) for p in record.get("excluded_ns", [])], points)


def prepare_gui(adapter, sequence, root: Path):
    check = getattr(adapter, "check_gui_geometry", None)
    if check is not None:
        check(sequence[-1]["source_end_ns"])
    selected = []
    for index, child in enumerate(sequence):
        timestamp = child["observation_ns"]
        target = root / "frames" / f"{index:04d}.jpg"
        extract_video_frame(
            adapter.video_path,
            timestamp / 1e6,
            target,
            resize=FrameResizeSpec.limit_width(896),
            seek_timestamp=getattr(adapter, "source_video_seek_timestamp", False),
        )
        selected.append(
            {
                "index": index,
                "action": child["action"],
                "canonical_action": child["canonical_action"],
                "image": target.relative_to(root).as_posix(),
                "image_sha256": file_digest(target)["sha256"],
                "video_time_ms": timestamp / 1e6,
                "action_time_ns": child["trigger_ns"],
            }
        )
    return selected, [sequence[0]["observation_ns"], sequence[-1]["source_end_ns"]]
