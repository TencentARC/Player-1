"""Public inference, data and evaluation contract checks."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from PIL import Image

from player1.agents.inference import AgentConfig, GameAgent, ModelConfig, PlayerOnePolicy
from player1.evaluation.common import EvaluationConfig, identity, summarize
from player1.evaluation.gameworld.evaluate import build_episodes as gameworld_episodes
from player1.evaluation.minestudio.evaluate import build_episodes as minedojo_episodes
from player1.evaluation.vizdoom.evaluate import build_episodes as vizdoom_episodes
from player1.gym import list_games
from player1.runtime.observation import Observation


class RuntimeTests(unittest.TestCase):
    def test_native_http_tools_and_atomic_history_commit(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                allowed = {"role", "content", "reasoning_content", "tool_calls", "tool_call_id", "name"}
                if any(set(message) - allowed for message in requests[-1]["messages"]):
                    self.send_error(400, "Unsupported message fields")
                    return
                payload = {"choices": [{"message": {"content": None, "tool_calls": [{
                    "type": "function", "id": "step-action",
                    "function": {"name": "wait", "arguments": "{}"},
                }]}, "finish_reason": "tool_calls"}]}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            policy = PlayerOnePolicy(
                ModelConfig(model="Player-1-9B", endpoint=f"http://127.0.0.1:{server.server_port}/v1"),
                agent_factory=lambda: GameAgent(AgentConfig(
                    game_id="base_3d_aim", model_profile_id="qwen3.5-player1-control-v-a-baserl",
                )), action_format_retry_max=0,
            )
            policy.reset("Aim at the target", 7, {"max_decisions": 3, "history_context_turns": 2})
            image = Image.new("RGB", (64, 36), "blue")
            first = policy.act(image)
            self.assertTrue(first.valid)
            self.assertEqual(first.control_action["id"], "wait")
            with self.assertRaises(RuntimeError):
                policy.act(image)
            policy.commit_after_successful_step(first, Observation(image.copy()))
            second = policy.act(image)
            self.assertTrue(second.valid)
            self.assertGreater(len(requests[1]["messages"]), len(requests[0]["messages"]))
            image_part = requests[0]["messages"][-1]["content"][0]
            self.assertEqual(image_part["type"], "image_url")
            self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertEqual(requests[0]["tools"][0]["type"], "function")
            policy.commit_after_successful_step(second, Observation(image.copy()))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_transport_keeps_episode_metadata_local(self):
        from player1.agents.backend import _wire_messages
        messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}],
                     "reasoning_content": "Move ahead", "episode_id": "local", "request_revision": 3},
                    {"role": "tool", "content": "ok", "tool_call_id": "call-1", "receipt": {"step": 1}}]
        wire = _wire_messages(messages)
        self.assertEqual(wire[0], {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}],
                                   "reasoning_content": "Move ahead"})
        self.assertEqual(wire[1], {"role": "tool", "content": "ok", "tool_call_id": "call-1"})

    def test_environment_and_benchmark_ledgers(self):
        from player1.environments.browser.env import COLLECTION
        from player1.runtime.bootstrap import collection_root
        collection = json.loads((COLLECTION / "collection.json").read_text())
        self.assertEqual(collection["collection_id"], "player1-gym")
        self.assertEqual(collection_root(), COLLECTION.resolve())
        self.assertEqual(len(list_games()), 16)
        self.assertEqual(len(set(list_games())), 16)
        for benchmark, count, build in [
            ("minedojo", 2400, minedojo_episodes),
            ("vizdoom", 500, vizdoom_episodes),
            ("gameworld", 510, gameworld_episodes),
        ]:
            with self.subTest(benchmark=benchmark):
                jobs = build()
                self.assertEqual(len(jobs), count)
                self.assertEqual(len({job["episode_id"] for job in jobs}), count)
                selected = build(tasks=[jobs[0]["task_id"]], trials=1)
                self.assertEqual(selected[0]["seed"], jobs[0]["seed"])

    def test_partial_coverage_and_revision_identity(self):
        jobs = [{"task_id": "a", "benchmark": "vizdoom"},
                {"task_id": "b", "benchmark": "vizdoom"}, {"task_id": "b", "benchmark": "vizdoom"}]
        results = [{"task_id": "a", "complete": True, "score": 1.0},
                   {"task_id": "b", "complete": True, "score": 0.0},
                   {"task_id": "b", "complete": False}]
        report = summarize(jobs, results)
        self.assertFalse(report["complete"])
        self.assertEqual(report["infrastructure_failures"], 1)
        self.assertEqual(report["mean_task_score"], 0.5)
        args = EvaluationConfig(model="Player-1-9B", model_revision="checkpoint-a")
        first = identity(args, jobs)
        args.model_revision = "checkpoint-b"
        self.assertNotEqual(identity(args, jobs), first)


class DatasetTests(unittest.TestCase):
    def test_full_release_validation_and_corruption_detection(self):
        from player1.datasets.dataset import Dataset
        from tests.release_fixture import build_release
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            manifest = build_release(root)
            dataset = Dataset(root)
            try:
                self.assertEqual(dataset.manifest, manifest)
                trajectories = list(dataset.trajectories())
                self.assertEqual([len(rows) for rows in trajectories], [50, 50])
                self.assertEqual(dataset.image(trajectories[0][0]["images"][0]).size, (64, 36))
            finally:
                dataset.close()
            validation = Dataset(root, split="validation")
            try:
                self.assertEqual(list(validation.trajectories()), [])
            finally:
                validation.close()
            image = root / "images" / trajectories[0][0]["images"][0]["image"]
            image.write_bytes(b"broken")
            with self.assertRaises(ValueError):
                Dataset(root)

    def test_trajectory_boundaries_and_image_resolution(self):
        from player1.datasets.dataset import Dataset
        from tests.release_fixture import build_release
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"
            build_release(root)
            dataset = Dataset(root)
            try:
                self.assertEqual([len(items) for items in dataset.trajectories()], [50, 50])
                self.assertEqual(dataset[50]["history_context"]["prior_sample_ids"], [])
                reference = dataset.stored_row(0)["images"][0]
                self.assertEqual(dataset.image(reference).size, (64, 36))
                with self.assertRaises(ValueError):
                    dataset.image({**reference, "image": "../outside.png"})
            finally:
                dataset.close()


if __name__ == "__main__":
    unittest.main()
