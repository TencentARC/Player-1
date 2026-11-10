"""Canonical browser input ownership across successful, failed and cancelled steps."""
import asyncio
from types import SimpleNamespace

import pytest

from player1.environments.browser.action_executor import (
    GET_VISIBLE_GAME_GEOMETRY_SCRIPT,
    NATIVE_INPUT_WINDOW_SCRIPT,
    PLAYER1_STEP_ACTION_SCRIPT,
    InputActionExecutor,
)


class Page:
    def __init__(self):
        self.events = []
        self.steps = []
        self.failure = None
        self.reject = False
        self.malformed = False
        self.mouse = SimpleNamespace(**{
            name: self.event(name) for name in ("down", "up", "move", "wheel")
        })

    def event(self, name):
        async def record(*args, **kwargs):
            self.events.append((name, args, kwargs))
        return record

    async def evaluate(self, script, args=None):
        if script == GET_VISIBLE_GAME_GEOMETRY_SCRIPT:
            return {"protocol": "visible_game_geometry_v1", "units": "css_pixels",
                    "left": 10, "top": 20, "width": 800, "height": 450}
        if script == PLAYER1_STEP_ACTION_SCRIPT:
            self.steps.append(args)
            if self.failure:
                raise self.failure
            return {"ok": not self.reject, "result": {} if self.malformed else {
                "state": {"schemaVersion": "2.0", "gameId": "test", "status": "playing", "game_state": {},
                          "seed": 1, "is_actionable": True, "terminal": {"isTerminal": False},
                          "metrics": {"env_reward_step": 0, "env_reward_episode": 0, "primary_score": 0}},
                "observation": {}, "reward": 0, "done": False,
                "info": {"action": {"type": "game_step_action", "id": "control"}},
            }}
        if script == NATIVE_INPUT_WINDOW_SCRIPT:
            self.events.append(("native", args))
            return True
        self.events.append(("hook", args))
        return True


def action(**fields):
    return {"type": "game_step_action", "id": "control", "duration_ms": 200, **fields}


def test_absolute_hold_relative_transition_scroll_and_release():
    async def run():
        page = Page()
        executor = InputActionExecutor(page)
        absolute_hold = action(mouse={"mode": "absolute", "x": 500, "y": 500},
                               mouse_hold={"button": "left"}, key_hold=["w"], scroll={"dx": 0, "dy": 120})
        await executor.execute(absolute_hold, pause_around_virtual_time=True, observation_size=(800, 450))
        assert ("move", (410.0, 245.0), {}) in page.events
        assert ("wheel", (0.0, 120.0), {}) in page.events
        assert page.steps[-1]["action"] == {"id": "control", "key_hold": ["w"]}
        assert page.steps[-1]["observationSize"] == (800, 450)
        assert "mouse" in absolute_hold  # Execution does not mutate the admitted action.
        await executor.execute(action(mouse_hold={"button": "left"}), pause_around_virtual_time=True)
        assert sum(event[0] == "down" for event in page.events) == 1
        relative = {"mode": "relative", "dx": 20, "dy": 0}
        await executor.execute(action(mouse=relative, mouse_hold={"button": "left"}), pause_around_virtual_time=True)
        assert page.steps[-1]["action"]["mouse"] == relative
        assert "mouse_hold" not in page.steps[-1]["action"]
        await executor.execute(action(id="wait"), pause_around_virtual_time=True)
        assert sum(event[0] == "up" for event in page.events) == 1
        await executor.release_held_inputs()
        assert sum(event[0] == "up" for event in page.events) == 1
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["exception", "rejection", "cancellation", "malformed_receipt"])
def test_failed_step_releases_mouse_and_native_input_window(failure):
    async def run():
        page = Page()
        if failure == "malformed_receipt":
            page.malformed = True
            error_type = ValueError
        elif failure == "rejection":
            page.reject = True
            error_type = RuntimeError
        else:
            error_type = asyncio.CancelledError if failure == "cancellation" else RuntimeError
            page.failure = error_type("step failed")
        executor = InputActionExecutor(page)
        with pytest.raises(error_type):
            await executor.execute(action(mouse={"mode": "absolute", "x": 0, "y": 0},
                                          mouse_hold={"button": "left"}), pause_around_virtual_time=True)
        assert ("up", (), {"button": "left"}) in page.events
        assert ("native", "abort") in page.events
        assert ("hook", "__pauseGame") in page.events
    asyncio.run(run())
