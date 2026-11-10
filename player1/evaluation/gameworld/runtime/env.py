"""Environment lifecycle and browser/game integration for runtime loops."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from env import (
    ActionExecutor,
    BrowserConfig,
    BrowserGameManager,
    GameLauncher,
    GameStateSnapshot,
    GameStateTracker,
    build_game_state_tracker,
)
from env.game_launcher import append_url_suffix
from env.runtime_pool import (
    GameWorldBrowserKey,
    GameWorldBrowserLease,
    GameWorldBrowserPool,
)

from .runtime_config import RuntimeConfig
from .game_agent import ActionPayload, Agent

LOGGER = logging.getLogger(__name__)

DEFAULT_READY_TIMEOUT_S = 60.0
DEFAULT_RESET_API_TIMEOUT_S = 20.0
DEFAULT_PAUSE_TIMEOUT_S = 5.0


class GameEnv:
    """Browser environment manager (server + browser + state tracking)."""

    def __init__(
        self,
        config: RuntimeConfig,
        headless: bool | None = None,
        port: int | None = None,
        browser_pool: GameWorldBrowserPool | None = None,
    ):
        self.config = config
        self.headless = self._resolve_headless(headless)
        self.port = port
        self.browser_pool = browser_pool
        self.browser_lease: GameWorldBrowserLease | None = None
        self.game_launcher: GameLauncher | None = None
        self.game_url: str | None = None
        self.game_manager: BrowserGameManager | None = None
        self.state_tracker: GameStateTracker = build_game_state_tracker()

        self._frame_counter = 0
        self._browser_lock = asyncio.Lock()
        self._executors: dict[str, ActionExecutor] = {}
        self._run_id = f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self._episode_id = self._next_episode_id()

    @staticmethod
    def _resolve_headless(headless: bool | None) -> bool:
        if headless is not None:
            return bool(headless)
        if os.name == "nt":
            return False
        return not bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    def _build_game_url(self) -> str:
        if self.config.url:
            game_url = self.config.url
        elif self.browser_pool is not None:
            game_url = self.browser_pool.game_url(self.config.game_id, preferred_port=self.port)
        else:
            self.game_launcher = GameLauncher(self.config.game_id, port=self.port)
            game_url = self.game_launcher.start()

        if self.config.game_url_suffix:
            game_url = append_url_suffix(game_url, self.config.game_url_suffix)
        return game_url

    def _build_browser_config(self) -> BrowserConfig:
        if not self.game_url:
            raise RuntimeError("Game URL is not initialized.")
        return BrowserConfig(
            game_url=self.game_url,
            width=self.config.width,
            height=self.config.height,
            speed_multiplier=self.config.speed_multiplier,
            random_seed=self.config.random_seed,
            headless=self.headless,
        )

    def _require_game_manager(self) -> BrowserGameManager:
        if not self.game_manager:
            raise RuntimeError("Game manager is not initialized.")
        return self.game_manager

    @staticmethod
    def _normalize_action_batch(action: ActionPayload) -> list[dict]:
        return ActionExecutor.normalize_action_batch(action)

    def _attach_runtime_ids(self, snapshot: GameStateSnapshot | None) -> GameStateSnapshot | None:
        if not snapshot or not snapshot.state:
            return snapshot

        state = dict(snapshot.state)
        state["runId"] = self._run_id
        state["episodeId"] = self._episode_id
        return GameStateSnapshot(state=state, summary=self.state_tracker.summarize(state))

    async def start(self) -> None:
        self.game_url = self._build_game_url()
        if self.browser_pool is None:
            self.game_manager = BrowserGameManager(self._build_browser_config())
            await self.game_manager.start()
        else:
            browser_config = self._build_browser_config()
            key = GameWorldBrowserKey.from_config(self.config.game_id, browser_config)
            self.browser_lease = await self.browser_pool.acquire(key, browser_config)
            self.game_manager = self.browser_lease.manager
        ready = await self.wait_until_ready(stage="startup", timeout_s=DEFAULT_READY_TIMEOUT_S)
        if not ready:
            raise RuntimeError(f"Startup readiness gate failed for {self.config.game_id}")

    @property
    def runtime_reused(self) -> bool:
        return bool(self.browser_lease and self.browser_lease.reused)

    async def close_game(self, *, reusable: bool = True) -> None:
        if self.browser_pool is not None and self.browser_lease is not None:
            lease, self.browser_lease = self.browser_lease, None
            await self.browser_pool.release(lease, reusable=reusable)
            self.game_manager = None
        elif self.game_manager:
            await self.game_manager.close()
            self.game_manager = None
        if self.game_launcher:
            self.game_launcher.stop()
            self.game_launcher = None

    async def pause_game(self) -> dict[str, float | bool]:
        manager = self._require_game_manager()
        async with self._browser_lock:
            return await manager.pause_game()

    async def resume_game(self) -> dict[str, float | bool]:
        manager = self._require_game_manager()
        async with self._browser_lock:
            return await manager.resume_game()

    async def read_gameplay_clock(self) -> dict[str, float | bool]:
        manager = self._require_game_manager()
        async with self._browser_lock:
            return await manager.get_gameplay_clock()

    async def capture_screenshot(self, agent_id: str) -> Path:
        manager = self._require_game_manager()
        async with self._browser_lock:
            frame_name = f"frame_{self._frame_counter:06d}_{agent_id}.png"
            path = await manager.capture_screenshot(frame_name)
            self._frame_counter += 1
            LOGGER.info("Captured frame for %s -> %s", agent_id, path)
            return Path(path)

    def _get_executor(self, agent: Agent) -> ActionExecutor:
        manager = self._require_game_manager()
        if not manager.page:
            raise RuntimeError("Game page is unavailable.")
        executor = self._executors.get(agent.agent_id)
        if executor:
            return executor

        executor = ActionExecutor(manager.page, controls=agent.controls)
        self._executors[agent.agent_id] = executor
        return executor

    async def execute_action(
        self,
        agent: Agent,
        action: ActionPayload,
        *,
        already_normalized: bool = False,
    ) -> dict[str, float | str] | None:
        actions_to_execute = self._normalize_action_batch(action)
        if not actions_to_execute:
            return None

        async with self._browser_lock:
            executor = self._get_executor(agent)
            timings = await executor.execute_actions(
                actions_to_execute,
                already_normalized=already_normalized,
            )
        return timings[0] if timings else None

    @staticmethod
    def _next_episode_id() -> str:
        return f"ep_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    async def reset_game(self) -> bool:
        manager = self.game_manager
        if not manager:
            return False

        repause = self.config.pause_during_inference
        async with self._browser_lock:
            try:
                if repause:
                    await manager.resume_game()

                try:
                    async with asyncio.timeout(DEFAULT_RESET_API_TIMEOUT_S):
                        ok = await manager.reset_game()
                except TimeoutError as exc:
                    raise RuntimeError(
                        f"Game reset timed out after {DEFAULT_RESET_API_TIMEOUT_S:.1f}s"
                    ) from exc

                if not ok:
                    return False

                ready = await manager.wait_until_actionable(
                    stage="reset",
                    timeout_s=DEFAULT_READY_TIMEOUT_S,
                )
                if not ready:
                    LOGGER.task(
                        "Task eval: reset readiness gate failed (game=%s); stopping run",
                        self.config.game_id,
                    )
                    return False
            finally:
                if repause:
                    try:
                        async with asyncio.timeout(DEFAULT_PAUSE_TIMEOUT_S):
                            await manager.pause_game()
                    except TimeoutError as exc:
                        raise RuntimeError(
                            "Game pause timed out after reset "
                            f"({DEFAULT_PAUSE_TIMEOUT_S:.1f}s)"
                        ) from exc

            self._episode_id = self._next_episode_id()
            return True

    async def wait_until_ready(self, stage: str, timeout_s: float) -> bool:
        if not self.game_manager:
            return False
        return await self.game_manager.wait_until_actionable(stage=stage, timeout_s=timeout_s)

    async def capture_state(self) -> GameStateSnapshot | None:
        manager = self.game_manager
        if not manager or not manager.page:
            return None
        try:
            async with self._browser_lock:
                snapshot = await self.state_tracker.snapshot(manager.page)
            return self._attach_runtime_ids(snapshot)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Failed to capture game state: %s", exc)
            return None


__all__ = ["DEFAULT_READY_TIMEOUT_S", "GameEnv"]
