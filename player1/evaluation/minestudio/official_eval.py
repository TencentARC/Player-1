"""Minecraft action, observation and render-readiness helpers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from player1.environments.minestudio.input_manager import MLLMGameAgentMineStudioInputManager
from player1.environments.minestudio.input_semantics import install_player1_input_actionables
from player1.environments.minestudio.readiness import (
    RenderProbe,
    RenderReadyConfig,
    RenderReadyReport,
    wait_for_render_ready,
)


class OfficialActionAdapter:
    """Compile canonical Player-1 controls at the MineStudio boundary."""

    def __init__(self, *, visible_game_size: tuple[int, int]):
        self._mllm_input_manager = MLLMGameAgentMineStudioInputManager(visible_game_size=visible_game_size)

    @property
    def last_input_evidence(self) -> dict[str, Any] | None:
        return self._mllm_input_manager.last_evidence

    def reset(self) -> None:
        self._mllm_input_manager.reset()

    def verify_runtime(self) -> Path:
        return self._mllm_input_manager.verify_runtime()

    def prepare_simulator(self, simulator: Any) -> Any:
        install_player1_input_actionables(simulator)
        return simulator

    def bind_observation(self, image: Image.Image, info: Mapping[str, Any]) -> Image.Image:
        """Bind exactly the image returned to our policy, including downstream resizing."""
        self._mllm_input_manager.bind_observation(image.size, gui_open=bool(info.get("isGuiOpen", False)))
        return image

    def to_env_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        return self._mllm_input_manager.compile_control(action)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def pov_image(
    obs: Mapping[str, Any],
    info: Mapping[str, Any],
    *,
    source: str,
    prefer_render_pov: bool = False,
) -> Image.Image:
    """Copy the policy-facing MineStudio observation as RGB."""

    frame = _pov_frame(obs, info, prefer_render_pov=prefer_render_pov)
    if isinstance(frame, Image.Image):
        return frame.convert("RGB").copy()
    if not isinstance(frame, np.ndarray):
        raise TypeError(f"{source} MinecraftSim did not return an image array, got {type(frame)!r}")
    array = frame
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    if array.ndim != 3 or array.shape[2] < 3:
        raise ValueError(f"{source} observation has unsupported shape {array.shape!r}")
    return Image.fromarray(array[:, :, :3], mode="RGB")


def _pov_frame(
    obs: Mapping[str, Any],
    info: Mapping[str, Any],
    *,
    prefer_render_pov: bool,
) -> Image.Image | np.ndarray | None:
    candidates = (
        (info.get("pov"), info.get("image"), obs.get("pov"), obs.get("image"))
        if prefer_render_pov
        else (obs.get("image"), obs.get("pov"), info.get("image"), info.get("pov"))
    )
    return next((candidate for candidate in candidates if candidate is not None), None)


def wait_for_official_render_ready(
    simulator: Any,
    *,
    record: Callable[[Any, Any], None],
    config: RenderReadyConfig,
    source: str,
    prefer_render_pov: bool = False,
) -> RenderReadyReport:
    """Probe the raw MineRL env without consuming benchmark callback steps."""

    raw_env = getattr(simulator, "env", None)
    wrap_obs_info = getattr(simulator, "_wrap_obs_info", None)
    if raw_env is None or not callable(getattr(raw_env, "step", None)) or not callable(wrap_obs_info):
        raise RuntimeError(f"{source} MinecraftSim does not expose raw readiness probing")

    def advance(voxel_probe: Sequence[int]) -> RenderProbe:
        action = dict(raw_env.action_space.no_op())
        action["voxels"] = np.asarray(voxel_probe, dtype=np.int32)
        raw_obs, _reward, done, raw_info = raw_env.step(action)
        obs, info = wrap_obs_info(raw_obs, raw_info)
        from .execution import raise_for_minecraft_step_error

        raise_for_minecraft_step_error(info, source=f"{source} render-ready probe")
        record(obs, info)
        return RenderProbe(
            image=_pov_frame(
                obs,
                info,
                prefer_render_pov=prefer_render_pov,
            ),
            info=info,
            terminated=bool(done),
            truncated=bool(done),
        )

    return wait_for_render_ready(advance, config=config, source=source)


__all__ = ['OfficialActionAdapter', '_pov_frame', 'append_jsonl', 'pov_image', 'wait_for_official_render_ready']
