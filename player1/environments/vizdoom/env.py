"""Direct ViZDoom runtime shared by evaluation and the local player."""

from __future__ import annotations

import importlib.metadata
import math
import os
import tempfile
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .actions import VizDoomAction
from .suite import (
    DEFAULT_EPISODE_TIMEOUT_TICS,
    DEFAULT_FRAME_SKIP_TICS,
    RENDER_RESOLUTION,
    RENDER_RESOLUTION_NAME,
    TURN_DELTA_DEGREES,
    VIZDOOM_VERSION,
    MapSpec,
    require_assets,
)


_VIZDOOM_INIT_LOCK = threading.Lock()


@contextmanager
def _isolated_vizdoom_working_directory(path: Path):
    """Launch Doom from a private cwd so its hard-coded cache is per environment."""

    with _VIZDOOM_INIT_LOCK:
        original_cwd_fd = os.open(".", os.O_RDONLY)
        try:
            os.chdir(path)
            yield
        finally:
            os.fchdir(original_cwd_fd)
            os.close(original_cwd_fd)


@dataclass(frozen=True)
class VizDoomStep:
    image: Image.Image
    reward: float
    terminated: bool
    truncated: bool
    info: dict[str, Any]


def require_vizdoom() -> Any:
    try:
        installed = importlib.metadata.version("vizdoom")
        import vizdoom
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise RuntimeError(
            f"ViZDoom evaluation requires vizdoom=={VIZDOOM_VERSION}; "
            "run python -m pip install -r requirements/vizdoom.txt from the repository root"
        ) from exc
    if installed != VIZDOOM_VERSION:
        raise RuntimeError(f"ViZDoom evaluation requires vizdoom=={VIZDOOM_VERSION}, found {installed}")
    return vizdoom


def _screen_image(screen_buffer: Any) -> Image.Image:
    import numpy as np

    frame = np.asarray(screen_buffer)
    if frame.ndim != 3:
        raise RuntimeError(f"ViZDoom screen buffer must be three-dimensional, got {frame.shape}")
    if frame.shape[0] in (3, 4) and frame.shape[-1] not in (3, 4):
        frame = np.moveaxis(frame, 0, -1)
    if frame.shape[-1] == 4:
        frame = frame[..., :3]
    if frame.shape[-1] != 3:
        raise RuntimeError(f"ViZDoom screen buffer must have three RGB channels, got {frame.shape}")
    return Image.fromarray(frame.astype(np.uint8, copy=False), mode="RGB")


def _button_name(button: Any) -> str:
    name = getattr(button, "name", None)
    if isinstance(name, str):
        return name
    return str(button).rsplit(".", 1)[-1]


class VizDoomEnv:
    """One deterministic direct-API environment with fixed tic timing."""

    def __init__(
        self,
        spec: MapSpec,
        *,
        seed: int,
        frame_skip_tics: int = DEFAULT_FRAME_SKIP_TICS,
        episode_timeout_tics: int = DEFAULT_EPISODE_TIMEOUT_TICS,
        window_visible: bool = False,
        config_path: Path | None = None,
        sound_enabled: bool = False,
        notifications_buffer_tics: int | None = None,
    ):
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("ViZDoom seed must be an integer")
        if frame_skip_tics <= 0 or episode_timeout_tics <= 0:
            raise ValueError("ViZDoom frame skip and episode timeout must be positive")
        if notifications_buffer_tics is not None and notifications_buffer_tics <= 0:
            raise ValueError("ViZDoom notifications buffer size must be positive")
        self.spec = spec
        self.seed = seed
        self.frame_skip_tics = frame_skip_tics
        self.episode_timeout_tics = episode_timeout_tics
        self.window_visible = window_visible
        self.config_path = config_path
        self.sound_enabled = sound_enabled
        self.notifications_buffer_tics = notifications_buffer_tics
        self._game: Any | None = None
        self._vizdoom: Any | None = None
        self._last_image: Image.Image | None = None
        self._runtime_dir: tempfile.TemporaryDirectory[str] | None = None

    def start(self) -> VizDoomStep:
        if self._game is not None:
            raise RuntimeError("ViZDoom environment is already started")
        vizdoom = require_vizdoom()
        config_path = self.config_path
        if config_path is None:
            if self.spec.config_source == "vendored":
                require_assets()
            config_path = self.spec.resolve_config_path(vizdoom)
        if not config_path.is_file():
            raise FileNotFoundError(f"Missing ViZDoom scenario config: {config_path}")
        runtime_dir = tempfile.TemporaryDirectory(prefix="player1-vizdoom-")
        game = None
        try:
            with _isolated_vizdoom_working_directory(Path(runtime_dir.name)):
                game = vizdoom.DoomGame()
                game.load_config(str(config_path))
                game.set_screen_resolution(getattr(vizdoom.ScreenResolution, RENDER_RESOLUTION_NAME))
                game.set_doom_config_path(str(Path(runtime_dir.name) / "_vizdoom.ini"))
                game.set_episode_timeout(self.episode_timeout_tics)
                game.set_window_visible(self.window_visible)
                if self.notifications_buffer_tics is not None:
                    game.set_notifications_buffer_enabled(True)
                    game.set_notifications_buffer_size(self.notifications_buffer_tics)
                if self.sound_enabled and game.is_audio_buffer_enabled():
                    # Audio capture suppresses device playback. The local player needs audible sound.
                    game.set_audio_buffer_enabled(False)
                game.set_sound_enabled(self.sound_enabled)
                game.set_seed(self.seed)
                game.init()
                game.new_episode()
        except BaseException:
            if game is not None:
                game.close()
            runtime_dir.cleanup()
            raise
        self._game = game
        self._vizdoom = vizdoom
        self._runtime_dir = runtime_dir
        return self._observation(reward=0.0)

    def _require_game(self) -> Any:
        if self._game is None:
            raise RuntimeError("Start the ViZDoom environment before using it")
        return self._game

    def _game_variables(self) -> dict[str, float]:
        game = self._require_game()
        variables: dict[str, float] = {}
        for variable in game.get_available_game_variables():
            name = _button_name(variable)
            try:
                variables[name] = float(game.get_game_variable(variable))
            except RuntimeError:
                continue
        return variables

    def _observation(self, *, reward: float) -> VizDoomStep:
        game = self._require_game()
        finished = bool(game.is_episode_finished())
        episode_time = int(game.get_episode_time())
        truncated = finished and episode_time >= self.episode_timeout_tics
        state = None if finished else game.get_state()
        if state is not None:
            self._last_image = _screen_image(state.screen_buffer)
            if self._last_image.size != RENDER_RESOLUTION:
                raise RuntimeError(
                    f"ViZDoom rendered {self._last_image.size}, expected shared resolution {RENDER_RESOLUTION}"
                )
        if self._last_image is None:
            raise RuntimeError("ViZDoom did not produce an initial RGB observation")
        info = {
            "map_id": self.spec.map_id,
            "map_name": self.spec.display_name,
            "seed": self.seed,
            "episode_time_tics": episode_time,
            "episode_timeout_tics": self.episode_timeout_tics,
            "frame_skip_tics": self.frame_skip_tics,
            "total_reward": float(game.get_total_reward()),
            "game_variables": self._game_variables(),
        }
        if state is not None:
            notifications = getattr(state, "notifications_buffer", None)
            if notifications:
                info["notifications"] = str(notifications)
        return VizDoomStep(
            image=self._last_image.copy(),
            reward=float(reward),
            terminated=finished and not truncated,
            truncated=truncated,
            info=info,
        )

    def _engine_action(self, action: VizDoomAction) -> list[float]:
        values = {
            "ATTACK": float(action.fire),
            "MOVE_FORWARD": float(action.move_forward),
            "MOVE_BACKWARD": float(action.move_backward),
            "MOVE_LEFT": float(action.strafe_left),
            "MOVE_RIGHT": float(action.strafe_right),
            "SPEED": float(action.speed),
            "TURN_LEFT": float(action.turn_left),
            "TURN_RIGHT": float(action.turn_right),
            # ViZDoom applies delta buttons once per tic. Split the requested
            # per-decision angle so frame skipping does not amplify it.
            "TURN_LEFT_RIGHT_DELTA": action.turn_delta * TURN_DELTA_DEGREES / self.frame_skip_tics,
        }
        if action.selected_weapon is not None:
            values[f"SELECT_WEAPON{action.selected_weapon}"] = 1.0
        return self._button_action(values)

    def _button_action(self, values: Mapping[str, float | int | bool]) -> list[float]:
        game = self._require_game()
        normalized: dict[str, float] = {}
        for name, value in values.items():
            if isinstance(value, bool):
                normalized[name] = float(value)
                continue
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"ViZDoom button value for {name} must be finite")
            normalized[name] = float(value)
        return [normalized.get(_button_name(button), 0.0) for button in game.get_available_buttons()]

    def available_button_names(self) -> tuple[str, ...]:
        game = self._require_game()
        return tuple(_button_name(button) for button in game.get_available_buttons())

    def step(self, action: VizDoomAction) -> VizDoomStep:
        if not isinstance(action, VizDoomAction):
            raise TypeError("ViZDoom step requires VizDoomAction")
        game = self._require_game()
        if game.is_episode_finished():
            raise RuntimeError("Cannot step a finished ViZDoom episode")
        reward = game.make_action(self._engine_action(action), self.frame_skip_tics)
        return self._observation(reward=float(reward))

    def step_buttons(self, values: Mapping[str, float | int | bool]) -> VizDoomStep:
        """Advance one local-player step using native ViZDoom button names."""

        game = self._require_game()
        if game.is_episode_finished():
            raise RuntimeError("Cannot step a finished ViZDoom episode")
        reward = game.make_action(self._button_action(values), self.frame_skip_tics)
        return self._observation(reward=float(reward))

    def close(self) -> None:
        game, self._game = self._game, None
        runtime_dir, self._runtime_dir = self._runtime_dir, None
        self._vizdoom = None
        self._last_image = None
        if game is not None:
            game.close()
        if runtime_dir is not None:
            runtime_dir.cleanup()

    def __enter__(self) -> VizDoomEnv:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["VizDoomEnv", "VizDoomStep", "require_vizdoom"]
