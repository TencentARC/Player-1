"""Game state tracking helpers and shared gameAPI scripts for browser games."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable

from playwright.async_api import Frame, Page


LOGGER = logging.getLogger(__name__)


GET_GAME_STATE_SCRIPT = """
() => {
    const api = window.gameAPI;
    if (!api) return null;
    if (typeof api.getState === "function") return api.getState();
    return null;
}
"""

GET_GAMEPLAY_CLOCK_SCRIPT = """() => {
    if (typeof window.__getGameSpeedState !== "function") return null;
    return window.__getGameSpeedState();
}"""

INIT_GAME_API_SCRIPT = """
async () => {
    const api = window.gameAPI;
    if (!api) return;
    if (typeof api.init === "function") {
        await api.init({});
    }
}
"""

RESET_GAME_API_SCRIPT = """
async () => {
    const api = window.gameAPI;
    if (!api || typeof api.reset !== "function") return false;
    const result = await api.reset({});
    if (result === true) return true;
    return !!(result && typeof result === "object" && result.ok === true);
}
"""

PAUSE_GAME_SCRIPT = """() => {
    if (typeof window.__pauseGame !== "function"
        || typeof window.__getGameSpeedState !== "function") {
        return { ok: false, isPaused: null };
    }
    window.__pauseGame();
    const s = window.__getGameSpeedState();
    const isPaused = s && s.isPaused;
    return {
        ok: isPaused === true,
        isPaused: isPaused,
        speedMultiplier: s && s.speedMultiplier,
        totalPausedTime: s && s.totalPausedTime,
        activeRealTimeMs: s && s.activeRealTimeMs,
        gameplayTimeMs: s && s.gameplayTimeMs
    };
}"""

RESUME_GAME_SCRIPT = """() => {
    if (typeof window.__resumeGame !== "function"
        || typeof window.__getGameSpeedState !== "function") {
        return { ok: false, isPaused: null };
    }
    window.__resumeGame();
    const s = window.__getGameSpeedState();
    const isPaused = s && s.isPaused;
    return {
        ok: isPaused === false,
        isPaused: isPaused,
        speedMultiplier: s && s.speedMultiplier,
        totalPausedTime: s && s.totalPausedTime,
        activeRealTimeMs: s && s.activeRealTimeMs,
        gameplayTimeMs: s && s.gameplayTimeMs
    };
}"""

PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT = """(function() {
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {
        if (type === "webgl" || type === "webgl2" || type === "experimental-webgl") {
            attrs = Object.assign({}, attrs || {}, { preserveDrawingBuffer: true });
        }
        return origGetContext.call(this, type, attrs);
    };
})();"""


@dataclass
class GameStateSnapshot:
    """Captured game state payload plus a concise summary."""

    state: dict | None
    summary: str


class GameStateTracker:
    """Base interface for game-state capture implementations."""

    name = "base"

    async def capture(self, page: Page | None) -> dict | None:
        raise NotImplementedError

    def _strip_nulls(self, value: object) -> object:
        if isinstance(value, dict):
            cleaned: dict = {}
            for key, item in value.items():
                cleaned_item = self._strip_nulls(item)
                if cleaned_item is None:
                    continue
                cleaned[key] = cleaned_item
            return cleaned or None
        if isinstance(value, list):
            cleaned_items = []
            for item in value:
                cleaned_item = self._strip_nulls(item)
                if cleaned_item is None:
                    continue
                cleaned_items.append(cleaned_item)
            return cleaned_items or None
        return value

    def _build_summary_state(self, state: dict | None) -> dict | None:
        if not state or not isinstance(state, dict):
            return None

        summary: dict = {}
        for key, value in state.items():
            if key in {"raw", "timestampMs", "schemaVersion"}:
                continue
            cleaned_value = self._strip_nulls(value)
            if cleaned_value is None:
                continue
            summary[key] = cleaned_value
        return summary or None

    def summarize(self, state: dict | None) -> str:
        """Create summary by including all fields except internal metadata.

        This is adaptive - any new field added to a game API automatically
        appears in the summary without manual configuration.
        """
        summary = self._build_summary_state(state)
        if not summary:
            return "(no game state)"
        return json.dumps(summary, ensure_ascii=False)

    async def snapshot(self, page: Page | None) -> GameStateSnapshot:
        state = await self.capture(page)
        raw_state = state if isinstance(state, dict) else None
        return GameStateSnapshot(state=raw_state, summary=self.summarize(raw_state))


class GameAPIStateTracker(GameStateTracker):
    """Capture game state from window.gameAPI.getState()."""

    name = "game_api"

    async def _evaluate_state(self, page: Page | Frame) -> dict | None:
        try:
            state = await page.evaluate(GET_GAME_STATE_SCRIPT)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Game state capture failed: %s", exc)
            return None
        if not isinstance(state, dict):
            return None
        return state

    @staticmethod
    def _candidate_pages(page: Page) -> Iterable[Page | Frame]:
        yield page
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            yield frame

    async def capture(self, page: Page | None) -> dict | None:
        if not page:
            return None

        for candidate in self._candidate_pages(page):
            state = await self._evaluate_state(candidate)
            if state:
                return state

        return None


def build_game_state_tracker() -> GameStateTracker:
    """Factory for selecting a game-state tracker."""
    return GameAPIStateTracker()


__all__ = [
    "GET_GAMEPLAY_CLOCK_SCRIPT",
    "GET_GAME_STATE_SCRIPT",
    "INIT_GAME_API_SCRIPT",
    "GameAPIStateTracker",
    "GameStateSnapshot",
    "GameStateTracker",
    "PAUSE_GAME_SCRIPT",
    "PRESERVE_WEBGL_DRAWING_BUFFER_SCRIPT",
    "RESET_GAME_API_SCRIPT",
    "RESUME_GAME_SCRIPT",
    "build_game_state_tracker",
]
