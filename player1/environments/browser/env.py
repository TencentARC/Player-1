"""Observation-based public interface to the shared Player-1-Gym browser runtime."""
from __future__ import annotations

import io
import json
from PIL import Image

from player1.runtime.bootstrap import DEFAULT_GAMES_ROOT
from player1.runtime.config import RuntimeConfig
from player1.runtime.observation import Observation
from .game_env import GameEnv

COLLECTION = DEFAULT_GAMES_ROOT


def list_games() -> list[str]:
    return [item["game_id"] for item in json.loads((COLLECTION / "collection.json").read_text())["games"]]


class GymEnv(GameEnv):
    def __init__(self, game_id: str, *, width: int = 854, height: int = 480, headless: bool = True):
        if game_id not in list_games():
            raise ValueError(f"Unknown game {game_id!r}; select one of {list_games()}")
        if width <= 0 or height <= 0:
            raise ValueError("Viewport dimensions must be positive")
        self.game_id = game_id
        super().__init__(RuntimeConfig(
            game_name=str(COLLECTION / game_id), game_id=game_id,
            width=width, height=height, random_seed=0, game_api_options={"autostart": True},
        ), headless=headless)
        self._last_observation = None
        self._done = False

    async def _image(self):
        screenshot = await self.capture_screenshot(selector="#display")
        with Image.open(io.BytesIO(screenshot)) as image:
            return image.convert("RGB")

    async def reset(self, *, seed: int = 0, options: dict | None = None) -> Observation:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("Seed must be an integer")
        self._last_observation = None
        self.config.random_seed = seed
        self.config.game_api_options = {**(options or {}), "autostart": True}
        if self.page is None:
            await self.start()
        else:
            await self.reset_game()
        state = await self.capture_state()
        self._done = False
        self._last_observation = Observation(
            await self._image(), info={"state": state, "game_id": self.game_id, "seed": seed},
        )
        return self._last_observation

    async def step(self, action: dict) -> Observation:
        if self._last_observation is None or self._done:
            raise RuntimeError("Reset the environment before stepping")
        result = await self.execute_runtime_step(
            action, pause_around_virtual_time=True, observation_size=self._last_observation.image.size,
        )
        self._done = result["done"]
        observation = Observation(
            await self._image(), float(result["reward"]), self._done, False,
            {**result["info"], "state": self.get_step_state(result), "game_id": self.game_id},
        )
        self._last_observation = observation
        return observation

    async def close(self):
        try:
            await self.close_game()
        finally:
            self._last_observation = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_args):
        await self.close()
