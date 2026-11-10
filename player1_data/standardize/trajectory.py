"""Prepare one immutable trajectory from recorded actions and causal source frames."""

from __future__ import annotations

import math
import shutil
import tempfile
from itertools import groupby
from pathlib import Path

from player1_data.files import (
    file_digest,
    fingerprint,
    publish_staged_immutable_directory,
    read_json,
    save_new_json,
)
from player1_data.sources.common import ACTION_DURATION_MS, FrameResizeSpec, SamplingConfig
from player1_data.sources.recording import ADAPTER_IDS
from player1_data.standardize.actions import frame_action
from player1_data.standardize.calibration import absolute, pixel_scroll_dy, relative, relative_mapping
from player1_data.standardize.keyboard import project_keyboard_timeline
from player1_data.standardize.mouse import project_mouse_button_timeline
from player1_data.standardize.temporal import build_source_action_partition


def pointer_arguments(samples, mapping, geometry):
    for sample in samples:
        for field, axes in (("mouse_delta", ("dx", "dy")), ("cursor", ("x", "y")), ("scroll", ("dx", "dy"))):
            vector = sample.get(field)
            if vector is None:
                continue
            if any(
                isinstance(vector.get(axis), bool)
                or not isinstance(vector.get(axis), (int, float))
                or not math.isfinite(vector[axis])
                for axis in axes
            ):
                raise ValueError(f"{field} coordinates must be finite numbers")
    pointers = [step.get("mouse_delta") for step in samples if step.get("mouse_delta")]
    cursors = [step.get("cursor") for step in samples if step.get("cursor")]
    arguments = {}
    if pointers:
        if mapping is None:
            raise ValueError("Relative motion has no calibrated source mapping")
        move = relative(sum(p["dx"] for p in pointers), sum(p["dy"] for p in pointers), mapping)
        if move:
            arguments["mouse_move"] = move
    elif cursors:
        point = cursors[-1]
        arguments["mouse_move"] = absolute(point["x"], point["y"], geometry["width_px"], geometry["height_px"])
    directions = set()
    for step in samples:
        scroll = step.get("scroll")
        if not scroll:
            continue
        if scroll.get("dx", 0):
            raise ValueError("Horizontal scrolling has no supported action")
        dy = pixel_scroll_dy(scroll.get("dy", 0), scroll.get("space"))
        if dy:
            directions.add("down" if dy > 0 else "up")
    if len(directions) > 1:
        raise ValueError("Opposite scroll directions cannot be combined into one recorded action")
    if directions:
        arguments["mouse_scroll"] = directions.pop()
    return arguments


def _ordinary(adapter, record, anchors, partition, root, calibrations):
    keyboard_timeline = adapter.source_native_keyboard_timeline(anchors, ACTION_DURATION_MS)
    mouse_timeline = adapter.source_native_mouse_button_timeline(anchors, ACTION_DURATION_MS)
    keyboard = project_keyboard_timeline(keyboard_timeline, partition)
    mouse = project_mouse_button_timeline(mouse_timeline, partition)
    result, mappings = [], []
    for index, (anchor, interval, keys, buttons) in enumerate(
        zip(anchors, partition.intervals, keyboard, mouse, strict=True)
    ):
        samples = adapter.pointer_samples(anchor, interval)
        geometry = adapter.observation_geometry(anchor)
        has_relative = any(step.get("mouse_delta") for step in samples)
        mapping = None
        if has_relative:
            key = tuple(sorted(geometry.items()))
            if key not in calibrations:
                calibrations[key] = relative_mapping(
                    record["source"], adapter.session.session_id, geometry, record.get("calibration")
                )
            mapping = calibrations[key]
            if mapping not in mappings:
                mappings.append(mapping)
        arguments = pointer_arguments(samples, mapping, geometry)
        arguments.update({key: keys[key] for key in ("key_hold", "key_tap") if keys[key]})
        arguments.update({key: buttons[key] for key in ("mouse_hold", "mouse_click") if buttons[key]})
        frame, action = frame_action(arguments)
        picture = adapter.materialize_frame(anchor, 0, root, resize=FrameResizeSpec.limit_width(896))
        if picture is None or picture.video_time_ms > anchor.video_time_ms + 1e-6:
            raise ValueError("Current observation is missing or comes from the future")
        image_path = picture.path.resolve()
        if not image_path.is_relative_to(root.resolve()):
            raise ValueError("Prepared image escaped its trajectory directory")
        digest = file_digest(image_path)
        result.append(
            {
                "index": index,
                "action": frame,
                "canonical_action": action,
                "image": image_path.relative_to(root.resolve()).as_posix(),
                "image_sha256": digest["sha256"],
                "video_time_ms": picture.video_time_ms,
                "action_time_ns": interval.start_ns,
            }
        )
    return result, [partition.coverage_start_ns, partition.coverage_end_ns], mappings


def prepare_recording(adapter, record, work: Path):
    """Prepare selected trajectories once per recording; accept only unchanged raw inputs."""
    from player1_data.standardize.gui import gui_trajectories, prepare_gui

    kind = record.get("mode", "gameplay")
    files = [file_digest(p) for p in adapter.session.source_files]
    count = record.get("count", 1)
    if kind == "gameplay":
        anchors = tuple(
            adapter.iter_anchors(SamplingConfig(start_time_ms=record.get("start_ms", 2000), max_samples=count * 50))
        )
        if len(anchors) != count * 50:
            raise ValueError("Recording does not contain the requested 50 complete action windows")
    parent = (work / "trajectories").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    prepared, pending, calibrations = [], [], {}
    choices, selected_ordinal = None, -1
    try:
        for ordinal in range(count):
            if kind == "gameplay":
                selected = anchors[ordinal * 50 : (ordinal + 1) * 50]
                partition = build_source_action_partition(
                    tuple(adapter.source_native_action_clock_ns(anchor) for anchor in selected),
                    onset_owner_policy=adapter.source_native_onset_owner_policy,
                )
            identity = {
                "adapter_id": ADAPTER_IDS[record["source"]],
                "dataset_id": adapter.session.dataset_id,
                "source_revision": adapter.session.source_revision,
                "session_id": adapter.session.session_id,
                "trajectory_id": f"{kind}-{ordinal:06d}-"
                + fingerprint({"input": str(record["input"]), "start": record.get("start_ms", 2000)})[:16],
            }
            binding = fingerprint(
                {
                    "recording": {k: v for k, v in record.items() if k != "count"},
                    "source_files": files,
                    "ordinal": ordinal,
                    "preparation": "gui_final_turns" if kind == "gui" else "player1-data",
                }
            )
            root = parent / fingerprint(identity)[:24]
            if root.exists():
                saved = read_json(root / "prepared.json")
                trajectory = saved["trajectory"]
                if saved["sha256"] != fingerprint(trajectory) or trajectory["binding"] != binding:
                    raise ValueError("Prepared trajectory or source inputs changed; use a new work directory")
                if kind == "gameplay" and (
                    [turn["action_time_ns"] for turn in trajectory["turns"]]
                    != [interval.start_ns for interval in partition.intervals]
                    or trajectory["source_span_ns"] != [partition.coverage_start_ns, partition.coverage_end_ns]
                ):
                    raise ValueError("Prepared trajectory has a different action schedule; use a new work directory")
                for turn in trajectory["turns"]:
                    if file_digest(root / turn["image"])["sha256"] != turn["image_sha256"]:
                        raise ValueError("A prepared observation changed")
            else:
                staging = Path(tempfile.mkdtemp(prefix=".preparing-", dir=parent)).resolve()
                pending.append((root, staging))
                if kind == "gui":
                    if choices is None:
                        choices = iter(gui_trajectories(adapter, record))
                    while selected_ordinal < ordinal:
                        sequence = next(choices, None)
                        if sequence is None:
                            raise ValueError("Recording does not contain the requested complete GUI trajectory")
                        selected_ordinal += 1
                    turns, span = prepare_gui(adapter, sequence, staging)
                    mappings = []
                else:
                    turns, span, mappings = _ordinary(adapter, record, selected, partition, staging, calibrations)
                check_trajectory(turns, kind=kind, **record.get("filter", {}))
                trajectory = {
                    "identity": identity,
                    "kind": kind,
                    "game": record["game"],
                    "binding": binding,
                    "turns": turns,
                    "source_span_ns": span,
                    "calibration": mappings,
                }
                save_new_json(staging / "prepared.json", {"sha256": fingerprint(trajectory), "trajectory": trajectory})
            prepared.append((root, trajectory))
        if [file_digest(p) for p in adapter.session.source_files] != files:
            raise ValueError("Raw recording changed during preparation")
        for root, staging in pending:
            publish_staged_immutable_directory(root, staging, field="prepared trajectory")
        return prepared
    finally:
        for _, staging in pending:
            if staging.exists():
                if staging.parent != parent:
                    raise ValueError("Unexpected staging cleanup path")
                shutil.rmtree(staging)


def check_trajectory(turns, *, kind, maximum_wait_ratio=0.1, maximum_repeat_ratio=0.98):
    expected = len(turns)
    if kind == "gameplay" and expected != 50 or kind == "gui" and not 25 <= expected <= 50:
        raise ValueError("A gameplay trajectory requires 50 turns; a GUI trajectory requires 25–50")
    if not 0 <= maximum_wait_ratio <= 1 or not 0 <= maximum_repeat_ratio <= 1:
        raise ValueError("Filter ratios must be in [0,1]")
    if any(t["index"] != i for i, t in enumerate(turns)):
        raise ValueError("Trajectory turns are not contiguous")
    if kind == "gameplay":
        waits = sum(t["action"].get("wait") is True for t in turns)
        if waits / expected > maximum_wait_ratio:
            raise ValueError("Trajectory rejected by the inactive-action filter")
        longest = max(sum(1 for _ in group) for _, group in groupby(t["canonical_action"] for t in turns))
        if longest / expected > maximum_repeat_ratio:
            raise ValueError("Trajectory rejected by the repeated-action filter")
