"""Shared normalization primitives for heterogeneous open gaming datasets."""

from __future__ import annotations

import csv
import json
import math
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from player1.datasets.player1_control import PLAYER1_CONTROL_DURATION_MS as ACTION_DURATION_MS
from player1_data.files import (
    _filesystem_path,
    _is_nonempty_file,
    _resolve_logical_path,
)
from player1_data.sources.media_tools import resolve_ffmpeg, resolve_ffprobe

_FFPROBE_TIMEOUT_SECONDS = 120
# One planned-frame probe process opens one independently-seeked input per
# request.  Give each request the same bounded decoder budget instead of
# making a multi-request batch share a single-request timeout.


class SourceQualificationError(ValueError):
    """A source defect with its original location and finite diagnostic evidence."""

    def __init__(self, diagnostic: str, *, reason_code: str, evidence: Mapping[str, Any]) -> None:
        if not isinstance(reason_code, str) or not reason_code:
            raise ValueError("source reason_code must be nonempty text")
        try:
            self.evidence = json.loads(json.dumps(dict(evidence), allow_nan=False))
        except (TypeError, ValueError) as error:
            raise ValueError("source evidence must be finite JSON") from error
        self.reason_code = reason_code
        super().__init__(diagnostic)


_CANONICAL_KEY_ALIASES = {
    "alt_l": "alt",
    "alt_left": "alt",
    "alt_r": "alt",
    "alt_right": "alt",
    "arrow_down": "arrowdown",
    "arrow_left": "arrowleft",
    "arrow_right": "arrowright",
    "arrow_up": "arrowup",
    "arrowdown": "arrowdown",
    "arrowleft": "arrowleft",
    "arrowright": "arrowright",
    "arrowup": "arrowup",
    "caps_lock": "capslock",
    "capslock": "capslock",
    "command": "meta",
    "control_l": "control",
    "control_left": "control",
    "control_r": "control",
    "control_right": "control",
    "ctrl": "control",
    "ctrl_l": "control",
    "ctrl_left": "control",
    "ctrl_r": "control",
    "ctrl_right": "control",
    "down": "arrowdown",
    "downarrow": "arrowdown",
    "esc": "escape",
    "left": "arrowleft",
    "left_alt": "alt",
    "leftalt": "alt",
    "left_control": "control",
    "leftcontrol": "control",
    "left_ctrl": "control",
    "left_meta": "meta",
    "leftmeta": "meta",
    "left_shift": "shift",
    "leftshift": "shift",
    "leftarrow": "arrowleft",
    "meta_l": "meta",
    "meta_left": "meta",
    "meta_r": "meta",
    "meta_right": "meta",
    "page_down": "pagedown",
    "page_up": "pageup",
    "pagedown": "pagedown",
    "pageup": "pageup",
    "right": "arrowright",
    "right_alt": "alt",
    "rightalt": "alt",
    "right_control": "control",
    "rightcontrol": "control",
    "right_ctrl": "control",
    "right_meta": "meta",
    "rightmeta": "meta",
    "right_shift": "shift",
    "rightshift": "shift",
    "rightarrow": "arrowright",
    "shift_l": "shift",
    "shift_left": "shift",
    "shift_r": "shift",
    "shift_right": "shift",
    "spacebar": "space",
    "super": "meta",
    "up": "arrowup",
    "uparrow": "arrowup",
    "win": "meta",
    "windows": "meta",
}


def canonical_key_name(value: Any) -> str:
    """Map source-specific key labels onto the Player-1 executor vocabulary."""

    normalized = str(value).strip().lower()
    normalized = normalized.removeprefix("key.")
    if normalized.startswith("keycode(char="):
        normalized = normalized.removeprefix("keycode(char=").removesuffix(")").strip("'\"")
    return _CANONICAL_KEY_ALIASES.get(normalized, normalized)


_MOUSE_BUTTON_NAMES = {1: "left", 2: "right", 3: "middle", 4: "back", 5: "forward"}


def canonical_mouse_button_name(value: Any) -> str:
    """Normalize the mouse-button names recorded by D2E and Gaming500."""

    if isinstance(value, int) and not isinstance(value, bool):
        return _MOUSE_BUTTON_NAMES.get(value, f"button_{value}")
    return str(value).lower()


@dataclass(frozen=True)
class FrameResizeSpec:
    """Width-capped, aspect-preserving image transform without crop or upscale."""

    max_width: int

    @classmethod
    def limit_width(cls, max_width: int) -> FrameResizeSpec:
        return cls(max_width)

    def __post_init__(self):
        if type(self.max_width) is not int or self.max_width <= 0:
            raise ValueError("max_width must be a positive integer")

    @property
    def cache_directory(self):
        return f"w{self.max_width}"

    @property
    def ffmpeg_scale_filter(self):
        return f"scale='min({self.max_width},iw)':-2"

    def projected_geometry(self, width_px: int, height_px: int):
        if any(type(v) is not int or v <= 0 for v in (width_px, height_px)):
            raise ValueError("source frame geometry must contain positive integer dimensions")
        width = min(self.max_width, width_px)
        height = 2 * ((height_px * width + width_px) // (2 * width_px))
        if height <= 0:
            raise ValueError("source frame geometry is too small for the even-dimension resize rule")
        return width, height


@dataclass(frozen=True)
class SamplingConfig:
    """Select the start and count of fixed 200 ms decisions with current/end frame context."""

    max_samples: int | None = 8
    start_time_ms: float = 0.0

    def __post_init__(self):
        if self.max_samples is not None and (type(self.max_samples) is not int or self.max_samples <= 0):
            raise ValueError("max_samples must be positive or null")
        if self.start_time_ms < 0 or not math.isfinite(self.start_time_ms):
            raise ValueError("start_time_ms must be nonnegative and finite")


@dataclass(frozen=True)
class SourceSession:
    dataset_id: str
    source_revision: str
    session_id: str
    game: str
    source_files: tuple[Path, ...]
    source_metadata: dict[str, Any]


@dataclass(frozen=True)
class SampleAnchor:
    video_time_ms: float
    source_index: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class MaterializedFrame:
    path: Path
    video_time_ms: float


_SourceFileKey = tuple[Path, int, int, int, int, int]


def _source_file_key(path: Path) -> _SourceFileKey:
    resolved = _resolve_logical_path(path, strict=True)
    stat = _filesystem_path(resolved).stat()
    return (
        resolved,
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def probe_immutable_source_video(path: Path) -> dict[str, Any]:
    before = _source_file_key(path)
    result = probe_video(path)
    if _source_file_key(path) != before:
        raise ValueError("Source video changed during metadata inspection")
    return result


def probe_immutable_source_video_frame_times_ms(path: Path) -> tuple[float, ...]:
    before = _source_file_key(path)
    result = probe_video_frame_times_ms(path)
    if _source_file_key(path) != before:
        raise ValueError("Source video changed during frame inspection")
    return result


def _parse_ffprobe_flat_output(output: str) -> dict[str, Any]:
    stream: dict[str, Any] = {}
    format_record: dict[str, Any] = {}
    for line_number, raw_line in enumerate(output.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        key, separator, encoded_value = line.partition("=")
        if not separator:
            raise ValueError(f"Invalid ffprobe flat output at line {line_number}: {raw_line!r}")
        try:
            value = json.loads(encoded_value)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid ffprobe flat value at line {line_number}: {encoded_value!r}") from error
        if key.startswith("streams.stream."):
            field = key.rsplit(".", maxsplit=1)[-1]
            stream[field] = value
        elif key.startswith("format."):
            format_record[key.removeprefix("format.")] = value
    return {"stream": stream, "format": format_record}


def _run_video_metadata_probe(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=_FFPROBE_TIMEOUT_SECONDS,
    )


def probe_video(path: Path) -> dict[str, Any]:
    path = _resolve_logical_path(path)
    ffprobe = resolve_ffprobe()
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:format=start_time,duration",
        "-of",
        "flat",
        str(path),
    ]
    try:
        result = _run_video_metadata_probe(command)
    except subprocess.TimeoutExpired:
        result = _run_video_metadata_probe(command)
    payload = _parse_ffprobe_flat_output(result.stdout)
    if not payload["stream"]:
        raise ValueError(f"Expected one video stream in {path}, found none")
    return payload


def probe_video_frame_times_ms(path: Path) -> tuple[float, ...]:
    path = _resolve_logical_path(path)
    ffprobe = resolve_ffprobe()
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "frame=best_effort_timestamp_time",
        "-of",
        "csv=p=0",
        str(path),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=_FFPROBE_TIMEOUT_SECONDS,
    )
    rows = [row for row in csv.reader(result.stdout.splitlines()) if any(field.strip() for field in row)]
    if not rows:
        raise ValueError(f"Video has no decoded frame timing records: {path}")
    frame_times_ms = []
    for index, row in enumerate(rows):
        values = [field.strip() for field in row if field.strip()]
        if len(values) != 1:
            raise ValueError(f"Video frame timing record {index} is ambiguous: {path}")
        try:
            frame_time_ms = float(values[0]) * 1_000.0
        except ValueError as error:
            raise ValueError(f"Video frame timing record {index} has no numeric PTS: {path}") from error
        if not math.isfinite(frame_time_ms) or frame_time_ms < 0:
            raise ValueError(f"Video frame timing record {index} has invalid PTS: {path}")
        if frame_times_ms and frame_time_ms <= frame_times_ms[-1]:
            raise ValueError(f"Video frame presentation times are not strictly increasing: {path}")
        frame_times_ms.append(frame_time_ms)
    return tuple(frame_times_ms)


def _full_range_jpeg_fallback_command(
    *,
    ffmpeg: str,
    video_path: Path,
    video_time_ms: float,
    output_path: Path,
    resize: FrameResizeSpec,
    seek_timestamp: bool = False,
) -> list[str]:
    resize_filter = resize.ffmpeg_scale_filter
    full_range_filter = "setrange=range=full" if resize_filter == "null" else f"{resize_filter}:out_range=full"
    # Some P2P recordings switch to limited-range yuv444p near the end of the
    # stream. FFmpeg's MJPEG encoder rejects that non-standard JPEG input, and
    # an exact input-side seek can also land too close to a damaged GOP edge to
    # emit a frame. Decode up to ten seconds of preroll to cross the longest
    # observed tail GOP and convert the missing output to a full-range JPEG.
    preroll_ms = min(video_time_ms, 10_000.0)
    fast_seek_ms = video_time_ms - preroll_ms
    command = [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
    ]
    if seek_timestamp:
        command.extend(["-seek_timestamp", "1"])
    command.extend(
        [
            "-ss",
            f"{fast_seek_ms / 1000:.6f}",
            "-i",
            str(video_path),
            "-ss",
            f"{preroll_ms / 1000:.6f}",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            full_range_filter,
            "-q:v",
            "2",
            "-y",
            str(output_path),
        ]
    )
    return command


def extract_video_frame(
    video_path: Path,
    video_time_ms: float,
    output_path: Path,
    *,
    resize: FrameResizeSpec,
    seek_timestamp: bool = False,
) -> None:
    if video_time_ms < 0:
        raise ValueError("video_time_ms must be nonnegative")
    ffmpeg = resolve_ffmpeg()
    _filesystem_path(output_path.parent.expanduser().absolute()).mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
    ]
    if seek_timestamp:
        command.extend(["-seek_timestamp", "1"])
    command.extend(
        [
            "-ss",
            f"{video_time_ms / 1000:.6f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            resize.ffmpeg_scale_filter,
            "-q:v",
            "2",
            "-y",
            str(output_path),
        ]
    )
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if _is_nonempty_file(output_path):
        result.check_returncode()
        return

    fallback_command = _full_range_jpeg_fallback_command(
        ffmpeg=ffmpeg,
        video_path=video_path,
        video_time_ms=video_time_ms,
        output_path=output_path,
        resize=resize,
        seek_timestamp=seek_timestamp,
    )
    subprocess.run(fallback_command, check=True, capture_output=True, text=True)
    if not _is_nonempty_file(output_path):
        raise RuntimeError(f"ffmpeg did not produce a frame: {output_path}")


def iter_sample_times(
    *,
    start_time_ms: float,
    end_time_ms: float,
    max_samples: int | None,
) -> Iterable[float]:
    if start_time_ms < 0 or end_time_ms < start_time_ms:
        raise ValueError("invalid sample time bounds")
    count = 0
    current = float(start_time_ms)
    while current <= end_time_ms + 1e-6 and (max_samples is None or count < max_samples):
        yield current
        current += ACTION_DURATION_MS
        count += 1
