"""GameWorld task selection, browser adapter and evaluation entrypoint."""

import json
from pathlib import Path

from ..common import policy_for, reset_policy, run_episodes

BENCHMARK = "gameworld"


def build_episodes(*, tasks=(), trials=3, max_steps=None):
    if trials <= 0 or max_steps is not None and max_steps <= 0:
        raise ValueError("Trial count and max steps must be positive")
    ledger = json.loads(Path(__file__).with_name("tasks.json").read_text())
    rows = []
    for task in ledger["trials"]:
        for index in range(trials):
            payload = {**task, "random_seed": index, "trial_index": index,
                       "max_steps": max_steps or task["max_steps"]}
            rows.append({"task_id": task["task_id"], "trial": index, "seed": index,
                         "max_steps": payload["max_steps"], "payload": payload})
    selected = set(tasks)
    missing = selected - {row["task_id"] for row in rows}
    if missing:
        raise ValueError(f"Unknown tasks: {sorted(missing)}")
    if selected:
        rows = [row for row in rows if row["task_id"] in selected]
    for row in rows:
        row["benchmark"] = BENCHMARK
        row["episode_id"] = f"{BENCHMARK}/{row['task_id']}/trial-{row['trial']:04d}"
    return rows


async def evaluate(config, *, games_root, tasks=(), trials=3, max_steps=None):
    episodes = build_episodes(tasks=tasks, trials=trials, max_steps=max_steps)
    return await run_episodes(config, episodes, lambda settings, job: _Episode(settings, job, games_root))


class _Episode:
    def __init__(self, args, job, games_root):
        from player1.environments.gameworld.env import GameWorldEnv
        from .scoring import build_task_evaluator
        if not games_root:
            raise ValueError("GameWorld evaluation requires games_root pointing to the benchmark folder")
        self.env = GameWorldEnv(job["payload"], games_root=games_root)
        self.policies = []
        for role in job["payload"]["roles"]:
            policy = policy_for(args, role["model_game_id"])
            reset_policy(policy, args, job, job["payload"]["task_prompt"])
            self.policies.append(policy)
        self.role_index = 0
        self.policy = self.policies[0]
        self.evaluate = build_task_evaluator(job["payload"]["evaluator_config"], max_steps=job["max_steps"])
        self.metrics = {}
        self.decisions = 0

    async def start(self):
        return await self.env.start()

    async def step(self, action):
        current = await self.env.step(action, role_index=self.role_index)
        self.decisions += 1
        evaluation = await self.evaluate(current.info["state"], self.decisions, self.metrics)
        if evaluation.status in {"error", "unknown"} and evaluation.should_stop:
            raise RuntimeError(evaluation.summary)
        self.metrics = dict(evaluation.metrics)
        current.reward = float(evaluation.status == "success")
        current.terminated = evaluation.should_stop
        current.truncated = evaluation.stop_reason == "max_steps_exhausted"
        current.info["evaluation"] = {"status": evaluation.status, "metrics": self.metrics}
        if evaluation.should_reset:
            from .scoring import reset_task_evaluator_episode_metrics
            self.metrics = reset_task_evaluator_episode_metrics(self.metrics)
            current = await self.env.reset()
        return current

    def after_commit(self):
        self.role_index = (self.role_index + 1) % len(self.policies)
        self.policy = self.policies[self.role_index]

    def score(self, current):
        return float(self.metrics.get("progress_best", self.metrics.get("progress", 0.0)))

    async def close(self):
        await self.env.close()
