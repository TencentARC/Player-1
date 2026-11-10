"""Direct MineStudio observation-readiness checks."""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

RENDER_READY_SCHEMA = "minecraft_render_ready_v1"


@dataclass(frozen=True)
class RenderReadyConfig:
    """Bounded direct-signal policy applied before the first model observation."""

    enabled: bool = False
    max_probe_frames: int = 120
    stable_frames: int = 5
    voxel_probe: tuple[int, int, int, int, int, int] = (-2, 2, -2, 2, -2, 2)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("render-ready enabled must be a boolean")
        if self.max_probe_frames <= 0:
            raise ValueError("render-ready max_probe_frames must be positive")
        if self.stable_frames <= 0 or self.stable_frames > self.max_probe_frames:
            raise ValueError("render-ready stable_frames must be in [1, max_probe_frames]")
        if len(self.voxel_probe) != 6 or any(not isinstance(value, int) for value in self.voxel_probe):
            raise ValueError("render-ready voxel_probe must contain six integers")
        for start, end in zip(self.voxel_probe[::2], self.voxel_probe[1::2], strict=True):
            if start > end or start < -50 or end > 50:
                raise ValueError("render-ready voxel_probe bounds must be ordered within [-50, 50]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RENDER_READY_SCHEMA,
            "enabled": self.enabled,
            "max_probe_frames": self.max_probe_frames,
            "stable_frames": self.stable_frames,
            "voxel_probe": list(self.voxel_probe),
        }


@dataclass(frozen=True)
class RenderProbe:
    """One neutral simulator step observed by the readiness gate."""

    image: Image.Image | np.ndarray | None
    info: Mapping[str, Any]
    terminated: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class RenderReadySample:
    probe_frame: int
    ready: bool
    failures: tuple[str, ...]
    stable_frames: int
    image_ready: bool
    pose_ready: bool
    voxel_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_frame": self.probe_frame,
            "ready": self.ready,
            "failures": list(self.failures),
            "stable_frames": self.stable_frames,
            "image_ready": self.image_ready,
            "pose_ready": self.pose_ready,
            "voxel_ready": self.voxel_ready,
        }


@dataclass(frozen=True)
class RenderReadyReport:
    ready: bool
    probe_frames: int
    elapsed_s: float
    required_stable_frames: int
    first_image_ready_frame: int | None
    first_pose_ready_frame: int | None
    first_voxel_ready_frame: int | None
    failure_counts: Mapping[str, int]
    last_sample: RenderReadySample

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RENDER_READY_SCHEMA,
            "ready": self.ready,
            "probe_frames": self.probe_frames,
            "elapsed_s": round(self.elapsed_s, 6),
            "required_stable_frames": self.required_stable_frames,
            "first_image_ready_frame": self.first_image_ready_frame,
            "first_pose_ready_frame": self.first_pose_ready_frame,
            "first_voxel_ready_frame": self.first_voxel_ready_frame,
            "failure_counts": dict(sorted(self.failure_counts.items())),
            "last_sample": self.last_sample.to_dict(),
        }


class RenderReadyTimeout(TimeoutError):
    """Raised when MineStudio never produces a complete direct observation."""

    def __init__(self, source: str, report: RenderReadyReport):
        self.source = source
        self.report = report
        failures = ", ".join(f"{name}={count}" for name, count in sorted(report.failure_counts.items())) or "none"
        super().__init__(
            f"{source} did not become render-ready after {report.probe_frames} neutral frames "
            f"({failures}); last={report.last_sample.to_dict()}"
        )


def _image_ready(image: Image.Image | np.ndarray | None) -> bool:
    # Structural availability only; pixel content is deliberately ignored.
    if isinstance(image, Image.Image):
        return image.width >= 8 and image.height >= 8
    if not isinstance(image, np.ndarray):
        return False
    return image.ndim == 3 and image.shape[2] >= 3 and min(image.shape[:2]) >= 8


def _finite_pose(info: Mapping[str, Any]) -> bool:
    player = info.get("player_pos")
    location = info.get("location_stats")
    player = player if isinstance(player, Mapping) else {}
    location = location if isinstance(location, Mapping) else {}
    values = (
        player.get("x", location.get("xpos")),
        player.get("y", location.get("ypos")),
        player.get("z", location.get("zpos")),
        player.get("yaw", location.get("yaw")),
        player.get("pitch", location.get("pitch")),
    )
    try:
        return all(value is not None and math.isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        return False


def _voxel_ready(info: Mapping[str, Any]) -> bool:
    voxels = info.get("voxels")
    if voxels is None:
        return False
    if isinstance(voxels, np.ndarray):
        return voxels.size > 0
    if isinstance(voxels, Mapping):
        return bool(voxels)
    if isinstance(voxels, Sequence) and not isinstance(voxels, (str, bytes)):
        return len(voxels) > 0
    return False


class RenderReadyDetector:
    """Require consecutive complete observations from the Minecraft client."""

    def __init__(self, config: RenderReadyConfig):
        self.config = config
        self._stable_frames = 0

    def observe(
        self,
        image: Image.Image | np.ndarray | None,
        info: Mapping[str, Any],
        *,
        probe_frame: int,
    ) -> RenderReadySample:
        image_ready = _image_ready(image)
        pose_ready = _finite_pose(info)
        voxel_ready = _voxel_ready(info)
        failures: list[str] = []
        if not image_ready:
            failures.append("image_missing")
        if not pose_ready:
            failures.append("pose_missing")
        if not voxel_ready:
            failures.append("voxel_probe_missing")

        if failures:
            self._stable_frames = 0
        else:
            self._stable_frames += 1
        ready = not failures and self._stable_frames >= self.config.stable_frames
        return RenderReadySample(
            probe_frame=probe_frame,
            ready=ready,
            failures=tuple(failures),
            stable_frames=self._stable_frames,
            image_ready=image_ready,
            pose_ready=pose_ready,
            voxel_ready=voxel_ready,
        )


def wait_for_render_ready(
    advance: Callable[[Sequence[int]], RenderProbe],
    *,
    config: RenderReadyConfig,
    source: str,
) -> RenderReadyReport:
    """Advance neutral frames until direct client signals are complete, or fail."""

    detector = RenderReadyDetector(config)
    failure_counts: Counter[str] = Counter()
    first_image_ready_frame = None
    first_pose_ready_frame = None
    first_voxel_ready_frame = None
    started_at = time.perf_counter()
    last_sample: RenderReadySample | None = None

    for probe_frame in range(1, config.max_probe_frames + 1):
        probe = advance(config.voxel_probe)
        if probe.terminated or probe.truncated:
            raise RuntimeError(f"{source} terminated during render-ready probing")
        sample = detector.observe(probe.image, probe.info, probe_frame=probe_frame)
        last_sample = sample
        failure_counts.update(sample.failures)
        if sample.image_ready and first_image_ready_frame is None:
            first_image_ready_frame = probe_frame
        if sample.pose_ready and first_pose_ready_frame is None:
            first_pose_ready_frame = probe_frame
        if sample.voxel_ready and first_voxel_ready_frame is None:
            first_voxel_ready_frame = probe_frame
        if sample.ready:
            return RenderReadyReport(
                ready=True,
                probe_frames=probe_frame,
                elapsed_s=time.perf_counter() - started_at,
                required_stable_frames=config.stable_frames,
                first_image_ready_frame=first_image_ready_frame,
                first_pose_ready_frame=first_pose_ready_frame,
                first_voxel_ready_frame=first_voxel_ready_frame,
                failure_counts=dict(failure_counts),
                last_sample=sample,
            )

    if last_sample is None:  # guarded by config validation
        raise AssertionError("render-ready probe loop did not execute")
    report = RenderReadyReport(
        ready=False,
        probe_frames=config.max_probe_frames,
        elapsed_s=time.perf_counter() - started_at,
        required_stable_frames=config.stable_frames,
        first_image_ready_frame=first_image_ready_frame,
        first_pose_ready_frame=first_pose_ready_frame,
        first_voxel_ready_frame=first_voxel_ready_frame,
        failure_counts=dict(failure_counts),
        last_sample=last_sample,
    )
    raise RenderReadyTimeout(source, report)


__all__ = [
    "RENDER_READY_SCHEMA",
    "RenderProbe",
    "RenderReadyConfig",
    "RenderReadyDetector",
    "RenderReadyReport",
    "RenderReadySample",
    "RenderReadyTimeout",
    "wait_for_render_ready",
]
