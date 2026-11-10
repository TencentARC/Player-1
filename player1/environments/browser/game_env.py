"""Shared browser lifecycle, actions, state, and PNG observations for Player-1-Gym."""

import asyncio
import io
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from PIL import Image
from playwright.async_api import async_playwright

from .contracts import (
    RUNTIME_HEALTH_PROBE_SCRIPT, RuntimeHealthExpectations, build_runtime_health_report,
)
from .action_executor import InputActionExecutor
from .server import AssetServer
from .state_tracker import GameAPIStateTracker, PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT


class GameEnv:
    def __init__(self, config, headless=None):
        self.config = config
        self.headless = True if headless is None else headless
        self.pause_during_inference = bool(config.pause_during_inference)
        self.page = self.browser = self.playwright = self.server = None
        self.state_tracker = GameAPIStateTracker()
        self._action_executor = None
        self._browser_lock = asyncio.Lock()
        self._run_id, self._episode_id = uuid4().hex, uuid4().hex

    def _options(self):
        options = dict(self.config.game_api_options)
        if self.config.random_seed is not None:
            options["seed"] = int(self.config.random_seed)
        suffix = self.config.game_url_suffix or ""
        if dict(parse_qsl(urlsplit(suffix).query)).get("autostart", "").lower() in {"1", "true", "yes", "on"}:
            options["autostart"] = True
        return options

    async def _initialize_episode(self, method):
        await self.page.evaluate("""async ({method, options, pause}) => {
            window.__resumeGame();
            try {
                const result = await window.gameAPI[method](options);
                if (result && result.ok === false) throw new Error('Game initialization failed');
            } finally {
                if (pause) window.__pauseGame();
            }
        }""", {"method": method, "options": self._options(), "pause": self.pause_during_inference})
        await self._check_health(method)

    async def start(self):
        if self.page is not None:
            return
        game_dir = Path(self.config.game_name).resolve(strict=True)
        self.server = AssetServer(game_dir.parent)
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless, args=["--enable-unsafe-swiftshader"],
            )
            context = await self.browser.new_context(
                viewport={"width": self.config.width, "height": self.config.height},
            )
            self.page = await context.new_page()
            self._action_executor = InputActionExecutor(self.page)
            await self.page.add_init_script(PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT)
            # Freeze wall-clock animation during model inference; API steps advance game time.
            clock = Path(__file__).with_name("scripts") / "dynamic_speed_control.js"
            await self.page.add_init_script(clock.read_text().replace("__INITIAL_SPEED_MULTIPLIER__", "1.0"))
            await self.page.goto(
                f"{self.server.url}/{game_dir.name}/index.html{self.config.game_url_suffix or ''}",
                wait_until="networkidle",
            )
            await self.page.wait_for_function("() => !!window.gameAPI && !!window.gameGymAPI", timeout=60000)
            await self._initialize_episode("init")
        except BaseException as error:
            try:
                await self.close_game()
            except BaseException as cleanup_error:
                error.add_note(f"Browser cleanup failed: {cleanup_error}")
            raise

    async def _check_health(self, stage):
        screenshot = await self.capture_screenshot()
        with Image.open(io.BytesIO(screenshot)) as image:
            width, height = image.size
        report = build_runtime_health_report(
            stage=stage, probe=await self.page.evaluate(RUNTIME_HEALTH_PROBE_SCRIPT),
            screenshot={
                "mime_type": "image/png", "encoded_mime_type": "image/png",
                "capture_backend": "playwright", "width": width, "height": height,
                "byte_length": len(screenshot), "error": None,
            },
            expectations=RuntimeHealthExpectations(
                game_id=self.config.game_id, viewport_width=self.config.width, viewport_height=self.config.height,
                random_seed=self.config.random_seed, training_reward_field=self.config.training_reward_field or None,
                require_virtual_time=True, require_pause=self.pause_during_inference,
            ),
            timing_ms=0.0,
        )
        report.require_healthy()

    async def close_game(self, *, outcome="ok"):
        try:
            if self.browser is not None:
                await self.browser.close()
        finally:
            try:
                if self.playwright is not None:
                    await self.playwright.stop()
            finally:
                if self.server is not None:
                    self.server.close()
                self.page = self.browser = self.playwright = self.server = None
                self._action_executor = None

    async def pause_game(self):
        await self.page.evaluate("() => window.__pauseGame()")

    async def resume_game(self):
        await self.page.evaluate("() => window.__resumeGame()")

    async def capture_screenshot(self, *, selector=None) -> bytes:
        """Capture the page or selected canvas as PNG bytes."""
        async with self._browser_lock:
            target = self.page.locator(selector) if selector else self.page
            return await target.screenshot(type="png")

    async def action_uses_virtual_time(self, action):
        return await self._action_executor.action_uses_virtual_time(action)

    async def execute_runtime_step(self, action, *, pause_around_virtual_time=False, observation_size=None):
        async with self._browser_lock:
            return await self._action_executor.execute(
                action, pause_around_virtual_time=pause_around_virtual_time, observation_size=observation_size,
            )

    def _prepare_state(self, state):
        state = self.state_tracker.normalize_state(state)
        if state is None:
            raise RuntimeError("Game did not return a structured state")
        return {**state, "runId": self._run_id, "episodeId": self._episode_id}

    def get_step_state(self, step_payload):
        return self._prepare_state(step_payload["state"])

    def summarize_state(self, state):
        return self.state_tracker.summarize(state)

    async def capture_state(self):
        return self._prepare_state(await self.page.evaluate("() => window.gameAPI.getState()"))

    async def reset_game(self):
        await self._action_executor.release_held_inputs()
        self._action_executor = InputActionExecutor(self.page)
        self._episode_id = uuid4().hex
        await self._initialize_episode("reset")
        return True
