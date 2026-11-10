"""Direct Playwright adapter for an installed GameWorld benchmark snapshot."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from player1.environments.browser.server import AssetServer
from player1.runtime.observation import Observation
from player1.runtime.types import RoleControls

from .control import GameGymControlExecutor

SCRIPTS = Path(__file__).parents[1] / "browser/scripts"


class GameWorldEnv:
    def __init__(self, trial, *, games_root, headless=True):
        self.trial = trial
        self.games_root = Path(games_root).expanduser().resolve(strict=True)
        self.headless = headless
        self.page = self.browser = self.playwright = self.server = None
        self.executors = []
        self._active_executor = None

    async def start(self):
        from playwright.async_api import async_playwright
        game = self.games_root / self.trial["game_id"] / "index.html"
        if not game.is_file():
            raise FileNotFoundError(f"GameWorld game entrypoint is absent: {game}")
        self.server = AssetServer(self.games_root)
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless, args=["--enable-unsafe-swiftshader"],
            )
            self.page = await self.browser.new_page(viewport={
                "width": self.trial["width"], "height": self.trial["height"],
            })
            await self.page.add_init_script((SCRIPTS / "deterministic_random.js").read_text().replace(
                "__RANDOM_SEED__", str(self.trial["random_seed"]),
            ))
            await self.page.add_init_script((SCRIPTS / "dynamic_speed_control.js").read_text().replace(
                "__INITIAL_SPEED_MULTIPLIER__", str(self.trial["speed_multiplier"]),
            ))
            url = f"{self.server.url}/{self.trial['game_id']}/index.html"
            suffix = self.trial.get("game_url_suffix") or ""
            await self.page.goto(url + suffix, wait_until="networkidle")
            await self.page.wait_for_function("() => !!window.gameAPI", timeout=60000)
            await self.page.evaluate("""async seed => {
                if (window.gameAPI.init) await window.gameAPI.init({seed});
                if (window.gameAPI.reset) await window.gameAPI.reset({seed});
                if (window.__pauseGame) window.__pauseGame();
            }""", self.trial["random_seed"])
            for role in self.trial["roles"]:
                controls = RoleControls(allowed_keys=set(role["allowed_keys"]),
                                        allow_clicks=role["allow_clicks"], hold_duration=role["hold_duration"],
                                        key_durations=role["key_durations"])
                self.executors.append(GameGymControlExecutor(self.page, controls))
            return await self.observe()
        except BaseException:
            await self.close()
            raise

    async def observe(self):
        state = await self.page.evaluate("() => window.gameAPI.getState()")
        if not isinstance(state, dict):
            raise RuntimeError("GameWorld getState() did not return a state object")
        data = await self.page.screenshot(type="png")
        with Image.open(io.BytesIO(data)) as image:
            return Observation(image.convert("RGB"), info={"state": state})

    async def step(self, action, *, role_index=0):
        try:
            executor = self.executors[role_index]
            if executor is not self._active_executor:
                await self._release_held_inputs()
                self._active_executor = executor
            try:
                await self.page.evaluate("() => { if (window.__resumeGame) window.__resumeGame(); }")
                await executor.execute(action)
            except BaseException as error:
                try:
                    await self.page.evaluate("() => { if (window.__pauseGame) window.__pauseGame(); }")
                except Exception as cleanup_error:
                    error.add_note(f"GameWorld pause failed: {type(cleanup_error).__name__}: {cleanup_error}")
                raise
            else:
                await self.page.evaluate("() => { if (window.__pauseGame) window.__pauseGame(); }")
            return await self.observe()
        except BaseException as error:
            try:
                await self._release_held_inputs()
            except Exception as cleanup_error:
                error.add_note(f"GameWorld input cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}")
            raise

    async def _release_held_inputs(self):
        if self._active_executor is not None:
            await self._active_executor.release_held_inputs()
            self._active_executor = None

    async def reset(self):
        await self._release_held_inputs()
        await self.page.evaluate("async () => { await window.gameAPI.reset({}); }")
        await self.page.evaluate("() => { if (window.__pauseGame) window.__pauseGame(); }")
        return await self.observe()

    async def close(self):
        try:
            try:
                await self._release_held_inputs()
            finally:
                if self.browser:
                    await self.browser.close()
        finally:
            try:
                if self.playwright:
                    await self.playwright.stop()
            finally:
                if self.server:
                    self.server.close()
                self.page = self.browser = self.playwright = self.server = None
                self.executors.clear()
                self._active_executor = None
