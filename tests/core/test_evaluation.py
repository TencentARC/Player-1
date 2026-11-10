"""Episode execution preserves history, failed attempts and completed results."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

from PIL import Image

from player1.evaluation.common import EvaluationConfig, run_episodes
from player1.runtime.observation import Observation


class EvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_gameworld_repeated_mouse_hold_drags_until_omitted(self):
        from player1.environments.gameworld.control import GameGymControlExecutor

        page = SimpleNamespace(mouse=AsyncMock(), viewport_size={"width": 801, "height": 451})
        controls = SimpleNamespace(allowed_keys=[], allow_clicks=True, hold_duration=0)
        executor = GameGymControlExecutor(page, controls)
        frame = {"type": "game_step_action", "mouse_hold": {"button": "left"}}
        await executor.execute({**frame, "mouse": {"mode": "absolute", "x": 0, "y": 0}})
        await executor.execute({**frame, "mouse": {"mode": "absolute", "x": 1000, "y": 1000}})
        await executor.execute({"type": "game_step_action", "mouse": {"mode": "absolute", "x": 500, "y": 500}})
        await executor.release_held_inputs()
        self.assertEqual(page.mouse.mock_calls, [
            call.move(0.0, 0.0), call.down(button="left"), call.move(800.0, 450.0),
            call.up(button="left"), call.move(400.0, 225.0),
        ])

    async def test_vizdoom_rejected_action_reports_mapping_reason(self):
        from player1.evaluation.vizdoom.evaluate import _Episode

        episode = object.__new__(_Episode)
        episode.spec = SimpleNamespace(map_id="basic")
        with self.assertRaisesRegex(ValueError, "basic: action_type_not_supported"):
            await episode.step({"type": "unsupported"})

    async def test_failed_step_retries_without_committing_and_completed_run_resumes(self):
        events = []
        fail_step = True
        job = {"benchmark": "vizdoom", "task_id": "basic", "trial": 0, "seed": 10000,
               "max_steps": 2, "episode_id": "vizdoom/basic/trial-0000"}

        class Episode:
            def __init__(self, _config, _job):
                self.policy = self
                self.image = Image.new("RGB", (64, 36), "blue")

            async def start(self):
                events.append("start")
                return Observation(self.image)

            def act(self, _image):
                events.append("act")
                return SimpleNamespace(control_action={"id": "wait"}, valid=True, invalid_reason=None,
                                       generation=SimpleNamespace(to_dict=lambda: {}))

            async def step(self, _action):
                events.append("step")
                if fail_step:
                    raise RuntimeError("Environment disconnected")
                return Observation(self.image, terminated=True)

            def commit_after_successful_step(self, _step, _current):
                events.append("commit")

            def after_commit(self):
                events.append("next-role")

            def score(self, _current):
                return 0.5

            async def close(self):
                events.append("close")

        with tempfile.TemporaryDirectory() as directory:
            config = EvaluationConfig(model="Player-1-9B", model_revision="test", output=Path(directory))
            report = await run_episodes(config, [job], Episode)
            self.assertFalse(report["complete"])
            self.assertEqual(report["infrastructure_failures"], 1)
            self.assertEqual(events, ["start", "act", "step", "close"])
            parent = config.output / job["episode_id"]
            self.assertTrue((parent / "attempt-0000/failure.json").exists())
            self.assertFalse((parent / "result.json").exists())

            fail_step = False
            events.clear()
            report = await run_episodes(config, [job], Episode)
            self.assertTrue(report["complete"])
            self.assertEqual(report["mean_task_score"], 0.5)
            self.assertEqual(events, ["start", "act", "step", "commit", "next-role", "close"])
            self.assertTrue((parent / "attempt-0001/step-0000.png").exists())
            receipt = json.loads((parent / "result.json").read_text())
            self.assertEqual(receipt["decisions"], 1)
            self.assertTrue(receipt["complete"])

            events.clear()
            self.assertEqual(await run_episodes(config, [job], Episode), report)
            self.assertEqual(events, [])
            config.model_revision = "other-checkpoint"
            with self.assertRaisesRegex(ValueError, "different model revision"):
                await run_episodes(config, [job], Episode)


if __name__ == "__main__":
    unittest.main()
