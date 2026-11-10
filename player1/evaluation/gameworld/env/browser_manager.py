"""Headless browser helpers for running HTML5 games in Playwright."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    CDPSession,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)
from .game_state_tracker import (
    GET_GAMEPLAY_CLOCK_SCRIPT,
    INIT_GAME_API_SCRIPT,
    PAUSE_GAME_SCRIPT,
    PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT,
    RESET_GAME_API_SCRIPT,
    RESUME_GAME_SCRIPT,
    GET_GAME_STATE_SCRIPT,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_GOTO_TIMEOUT_MS = 60000
DEFAULT_LOAD_STATE_TIMEOUT_MS = 5000
DEFAULT_READINESS_POLL_S = 0.3
BROWSER_SCRIPT_DIR = Path(__file__).with_name("browser_scripts")


def _load_browser_script(filename: str) -> str:
    return (BROWSER_SCRIPT_DIR / filename).read_text(encoding="utf-8").strip()


def _build_dynamic_speed_control_script(initial_speed_multiplier: float) -> str:
    return _load_browser_script("dynamic_speed_control.js").replace(
        "__INITIAL_SPEED_MULTIPLIER__",
        json.dumps(initial_speed_multiplier),
    )


def _build_deterministic_random_script(seed: int) -> str:
    return _load_browser_script("deterministic_random.js").replace(
        "__RANDOM_SEED__",
        json.dumps(seed),
    )


def _default_screenshot_dir() -> Path:
    return Path(".screenshots_temp") / f"{os.getpid()}_{uuid.uuid4().hex}"


class CDPScreenshotter:
    """Capture screenshots through a persistent CDP session."""

    def __init__(self):
        self._cdp_session: CDPSession | None = None

    async def capture(
        self,
        *,
        page: Page | None,
        target: Path,
        new_cdp_session: Callable[[], Awaitable[CDPSession]],
    ) -> Path:
        if not page:
            raise RuntimeError("Browser page is not initialized.")

        if self._cdp_session is None:
            self._cdp_session = await new_cdp_session()

        result = await self._cdp_session.send("Page.captureScreenshot")
        target.write_bytes(base64.b64decode(result["data"]))
        return target

    async def close(self) -> None:
        if not self._cdp_session:
            return
        try:
            await self._cdp_session.detach()
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("CDP detach skipped: %s", exc)
        finally:
            self._cdp_session = None


class BrowserReadinessGate:
    """Wait until a browser game reaches an actionable status."""

    @staticmethod
    def normalize_status(state: dict | None) -> str | None:
        if not isinstance(state, dict):
            return None
        raw_status = state.get("status")
        if not isinstance(raw_status, str):
            return None
        status = raw_status.strip().lower()
        return status or None

    @staticmethod
    def normalize_actionable(state: dict | None) -> bool | None:
        if not isinstance(state, dict) or "is_actionable" not in state:
            return None
        return state.get("is_actionable") is True

    async def wait_until_actionable(
        self,
        *,
        stage: str,
        timeout_s: float,
        actionable_statuses: tuple[str, ...],
        get_state: Callable[[], Awaitable[dict | None]],
        extra_wait_after_actionable_s: float = 0.1,
    ) -> bool:
        desired = {
            status.strip().lower() for status in actionable_statuses if isinstance(status, str)
        }
        if not desired:
            desired = {"playing"}

        started_at = time.monotonic()
        last_status: str | None = None
        last_actionable: bool | None = None

        while True:
            state = await get_state()
            status = self.normalize_status(state)
            actionable = self.normalize_actionable(state)

            if status != last_status or actionable != last_actionable:
                LOGGER.info(
                    "Game readiness (%s): status=%s is_actionable=%s",
                    stage,
                    status or "unavailable",
                    actionable,
                )
                last_status = status
                last_actionable = actionable

            ready = actionable if actionable is not None else status in desired
            if ready:
                LOGGER.info(
                    "Game readiness (%s): ready with status=%s is_actionable=%s after %.2fs",
                    stage,
                    status,
                    actionable,
                    time.monotonic() - started_at,
                )
                await asyncio.sleep(extra_wait_after_actionable_s)
                return True

            elapsed = time.monotonic() - started_at
            if elapsed >= timeout_s:
                LOGGER.warning(
                    "Game readiness (%s): timeout after %.2fs "
                    "(last status=%s, is_actionable=%s, desired=%s)",
                    stage,
                    elapsed,
                    status or "unavailable",
                    actionable,
                    sorted(desired),
                )
                return False

            await asyncio.sleep(DEFAULT_READINESS_POLL_S)


@dataclass
class BrowserConfig:
    """Configuration values for launching the browser."""

    game_url: str
    width: int = 1280
    height: int = 720
    headless: bool = False
    speed_multiplier: float = 1.0
    screenshot_dir: Path = field(default_factory=_default_screenshot_dir)
    random_seed: int | None = 42
    zoom_level: float = 1.0


class BrowserGameManager:
    """Launch a Chromium instance and prepare an HTML5 game session."""

    def __init__(self, config: BrowserConfig, *, browser_runtime: Any | None = None):
        self.config = config
        self._browser_runtime = browser_runtime
        self._shared_browser_reused = False
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._readiness = BrowserReadinessGate()
        self._screenshotter = CDPScreenshotter()

    async def __aenter__(self) -> "BrowserGameManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch Playwright and navigate to the configured game URL."""
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        await self._launch_browser()
        await self._install_page_scripts()
        await self._navigate_to_game()
        await self._maybe_init_game_api()

    @property
    def shared_browser_reused(self) -> bool:
        return self._shared_browser_reused

    @staticmethod
    def _browser_launch_args() -> list[str]:
        return [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
        ]

    async def _launch_browser(self) -> None:
        if self._browser_runtime is not None:
            self.browser, self._shared_browser_reused = await self._browser_runtime.acquire(
                headless=self.config.headless,
                args=self._browser_launch_args(),
            )
        else:
            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(
                headless=self.config.headless,
                args=self._browser_launch_args(),
            )
        self.context = await self.browser.new_context(
            viewport={"width": self.config.width, "height": self.config.height},
            service_workers="block",
        )
        self.page = await self.context.new_page()

        if self.config.zoom_level != 1.0:
            cdp_session = await self._new_cdp_session()
            try:
                await cdp_session.send(
                    "Emulation.setPageScaleFactor",
                    {"pageScaleFactor": self.config.zoom_level},
                )
            finally:
                await cdp_session.detach()

    async def _install_page_scripts(self) -> None:
        if not self.page:
            raise RuntimeError("Browser page is not initialized.")

        await self.page.add_init_script(PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT)
        await self.page.add_init_script(
            _build_dynamic_speed_control_script(self.config.speed_multiplier)
        )
        if self.config.random_seed is not None:
            await self.page.add_init_script(
                _build_deterministic_random_script(self.config.random_seed)
            )

    async def _navigate_to_game(self) -> None:
        if not self.page:
            raise RuntimeError("Browser page is not initialized.")

        goto_timeout_ms = int(
            os.environ.get("GAMEWORLD_PAGE_GOTO_TIMEOUT_MS", str(DEFAULT_GOTO_TIMEOUT_MS))
        )
        try:
            await self.page.goto(
                self.config.game_url,
                wait_until="domcontentloaded",
                timeout=goto_timeout_ms,
            )
        except PlaywrightError as exc:
            raise RuntimeError(f"Failed to open game URL {self.config.game_url}: {exc}") from exc

        try:
            await self.page.wait_for_load_state("load", timeout=DEFAULT_LOAD_STATE_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            LOGGER.debug(
                "Page load-state=load timed out after DOM ready: %s",
                self.config.game_url,
            )

    async def _new_cdp_session(self) -> CDPSession:
        if not self.context or not self.page:
            raise RuntimeError("Browser page is not initialized.")
        return await self.context.new_cdp_session(self.page)

    async def _maybe_init_game_api(self) -> None:
        if not self.page:
            return
        try:
            await self.page.evaluate(INIT_GAME_API_SCRIPT)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("gameAPI init failed: %s", exc)

    async def capture_screenshot(self, name: str) -> Path:
        """Capture a screenshot without triggering viewport flash in headed mode."""
        return await self._screenshotter.capture(
            page=self.page,
            target=self.config.screenshot_dir / name,
            new_cdp_session=self._new_cdp_session,
        )

    async def get_game_state(self) -> Optional[dict]:
        if not self.page:
            return None
        try:
            state = await self.page.evaluate(GET_GAME_STATE_SCRIPT)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Failed to read game state from gameAPI: %s", exc)
            return None
        return state if isinstance(state, dict) else None

    async def wait_until_actionable(
        self,
        stage: str,
        timeout_s: float = 60.0,
        actionable_statuses: tuple[str, ...] = ("ready", "playing"),
        extra_wait_after_actionable_s: float = 0.1,
    ) -> bool:
        """Wait until game status is actionable before agent interaction starts."""
        return await self._readiness.wait_until_actionable(
            stage=stage,
            timeout_s=timeout_s,
            actionable_statuses=actionable_statuses,
            get_state=self.get_game_state,
            extra_wait_after_actionable_s=extra_wait_after_actionable_s,
        )

    async def reset_game(self) -> bool:
        """Reset game state via gameAPI."""
        if not self.page:
            raise RuntimeError("Cannot reset game: browser page is unavailable.")
        try:
            did_reset = await self.page.evaluate(RESET_GAME_API_SCRIPT)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"gameAPI reset failed: {exc}") from exc
        return bool(did_reset)

    async def reload_game(self) -> bool:
        if not self.page:
            return False
        await self._screenshotter.close()
        try:
            await self.page.reload(
                wait_until="domcontentloaded",
                timeout=int(os.environ.get("GAMEWORLD_PAGE_GOTO_TIMEOUT_MS", str(DEFAULT_GOTO_TIMEOUT_MS))),
            )
            try:
                await self.page.wait_for_load_state("load", timeout=DEFAULT_LOAD_STATE_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                pass
            await self._maybe_init_game_api()
            return True
        except PlaywrightError as exc:
            LOGGER.debug("GameWorld pooled page reload failed: %s", exc)
            return False

    async def clear_input_state(self) -> None:
        if not self.page or self.page.is_closed():
            raise RuntimeError("Cannot clear input state: browser page is unavailable")
        for button in ("left", "right", "middle"):
            try:
                await self.page.mouse.up(button=button)
            except PlaywrightError:
                pass
        keys = (
            "ArrowUp",
            "ArrowDown",
            "ArrowLeft",
            "ArrowRight",
            "Space",
            "Enter",
            "Escape",
            "Shift",
            "Control",
            "Alt",
            "Tab",
            "Backspace",
            "Delete",
            *(chr(code) for code in range(ord("a"), ord("z") + 1)),
            *(str(number) for number in range(10)),
        )
        for key in keys:
            try:
                await self.page.keyboard.up(key)
            except PlaywrightError:
                pass
        await self.page.evaluate(
            "() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); }"
        )

    @staticmethod
    def _require_pause_transition(
        result: object,
        *,
        operation: str,
        expected_paused: bool,
    ) -> None:
        if (
            not isinstance(result, dict)
            or result.get("ok") is not True
            or result.get("isPaused") is not expected_paused
        ):
            raise RuntimeError(
                f"Game {operation} was not confirmed by the browser: {result!r}"
            )

    @staticmethod
    def _normalize_gameplay_clock(result: object) -> dict[str, float | bool]:
        if not isinstance(result, dict):
            raise RuntimeError(f"Browser gameplay clock is unavailable: {result!r}")

        numeric_fields = {
            "speed_multiplier": result.get("speedMultiplier"),
            "active_real_time_ms": result.get("activeRealTimeMs"),
            "gameplay_time_ms": result.get("gameplayTimeMs"),
            "total_paused_real_time_ms": result.get("totalPausedTime"),
        }
        if not isinstance(result.get("isPaused"), bool) or any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            for value in numeric_fields.values()
        ):
            raise RuntimeError(f"Browser gameplay clock is malformed: {result!r}")
        return {
            "is_paused": bool(result["isPaused"]),
            **{key: float(value) for key, value in numeric_fields.items()},
        }

    async def get_gameplay_clock(self) -> dict[str, float | bool]:
        """Read the pause-aware browser gameplay clock."""
        if not self.page:
            raise RuntimeError("Cannot read gameplay clock: browser page is unavailable.")
        try:
            result = await self.page.evaluate(GET_GAMEPLAY_CLOCK_SCRIPT)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Gameplay clock read failed: {exc}") from exc
        return self._normalize_gameplay_clock(result)

    async def pause_game(self) -> dict[str, float | bool]:
        """Pause the game and require the browser to confirm the transition."""
        if not self.page:
            raise RuntimeError("Cannot pause game: browser page is unavailable.")
        try:
            result = await self.page.evaluate(PAUSE_GAME_SCRIPT)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Game pause hook failed: {exc}") from exc
        self._require_pause_transition(
            result,
            operation="pause",
            expected_paused=True,
        )
        LOGGER.debug("Pause: %s", result)
        return self._normalize_gameplay_clock(result)

    async def resume_game(self) -> dict[str, float | bool]:
        """Resume the game and require the browser to confirm the transition."""
        if not self.page:
            raise RuntimeError("Cannot resume game: browser page is unavailable.")
        try:
            result = await self.page.evaluate(RESUME_GAME_SCRIPT)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Game resume hook failed: {exc}") from exc
        self._require_pause_transition(
            result,
            operation="resume",
            expected_paused=False,
        )
        LOGGER.debug("Resume: %s", result)
        return self._normalize_gameplay_clock(result)

    async def close(self) -> None:
        """Gracefully close browser resources and temporary screenshots."""
        await self._screenshotter.close()

        try:
            if self.page:
                try:
                    await self.page.close()
                except PlaywrightError as exc:
                    LOGGER.debug("Page close skipped: %s", exc)
        finally:
            self.page = None

        try:
            if self.context:
                try:
                    await self.context.close()
                except PlaywrightError as exc:
                    LOGGER.debug("Context close skipped: %s", exc)
        finally:
            self.context = None

        try:
            if self.browser and self._browser_runtime is None:
                try:
                    await self.browser.close()
                except PlaywrightError as exc:
                    LOGGER.debug("Browser close skipped: %s", exc)
        finally:
            self.browser = None

        try:
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.debug("Playwright stop skipped: %s", exc)
        finally:
            self._playwright = None

        try:
            if self.config.screenshot_dir.exists():
                shutil.rmtree(self.config.screenshot_dir, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Failed to clean screenshot dir %s: %s", self.config.screenshot_dir, exc)


__all__ = ["BrowserConfig", "BrowserGameManager"]
