"""Evaluate Player-1-Gym with the shared trace and screenshot format."""

from player1.catalog import load_task
from player1.gym import GymEnv, list_games

from .common import policy_for, reset_policy, run_episodes


def build_episodes(*, tasks=(), trials=1, max_steps=None, base_seed=10000):
    if trials <= 0 or max_steps is not None and max_steps <= 0:
        raise ValueError("Trial count and max steps must be positive")
    games = list_games()
    selected = set(tasks) if tasks else set(games)
    if selected - set(games):
        raise ValueError(f"Unknown Gym games: {sorted(selected - set(games))}")
    rows = []
    for game_index, game in enumerate(games):
        if game not in selected:
            continue
        task = load_task(game, f"{game}_train")
        for trial in range(trials):
            rows.append({"benchmark": "gym", "task_id": game, "trial": trial,
                         "seed": base_seed + game_index * 100000 + trial,
                         "max_steps": max_steps or task.max_steps,
                         "episode_id": f"gym/{game}/trial-{trial:04d}"})
    return rows


async def evaluate(config, *, tasks=(), trials=1, max_steps=None, base_seed=10000):
    jobs = build_episodes(tasks=tasks, trials=trials, max_steps=max_steps, base_seed=base_seed)
    return await run_episodes(config, jobs, _Episode)


class _Episode:
    def __init__(self, args, job):
        self.job = job
        self.env = GymEnv(job["task_id"])
        self.policy = policy_for(args, job["task_id"])
        task = load_task(job["task_id"], f"{job['task_id']}_train")
        reset_policy(self.policy, args, job, task.task_prompt)
        self.total_reward = 0.0

    async def start(self):
        return await self.env.reset(seed=self.job["seed"])

    async def step(self, action):
        current = await self.env.step(action)
        self.total_reward += current.reward
        return current

    def score(self, current):
        return self.total_reward

    async def close(self):
        await self.env.close()
