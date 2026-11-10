"""ViZDoom task selection, environment adapter and evaluation entrypoint."""

from ..common import policy_for, reset_policy, run_episodes

BENCHMARK = "vizdoom"


def build_episodes(*, tasks=(), trials=50, max_steps=None, base_seed=10000):
    from player1.environments.vizdoom.suite import suite_spec
    if trials <= 0 or max_steps is not None and max_steps <= 0:
        raise ValueError("Trial count and max steps must be positive")
    suite = suite_spec("vizdoom-10-maps")
    rows = []
    for spec in suite.maps:
        for index in range(trials):
            rows.append({"task_id": spec.map_id, "trial": index,
                         "seed": base_seed + suite.seed_index(spec.map_id) * 100000 + index,
                         "max_steps": max_steps or spec.default_max_decisions})
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


async def evaluate(config, *, tasks=(), trials=50, max_steps=None, base_seed=10000):
    episodes = build_episodes(tasks=tasks, trials=trials, max_steps=max_steps, base_seed=base_seed)
    return await run_episodes(config, episodes, _Episode)


class _Episode:
    def __init__(self, args, job):
        from player1.environments.vizdoom.env import VizDoomEnv
        from player1.environments.vizdoom.suite import suite_spec

        from .agent import VizDoomGameAgent
        self.spec = next(spec for spec in suite_spec("vizdoom-10-maps").maps if spec.map_id == job["task_id"])
        self.env = VizDoomEnv(self.spec, seed=job["seed"], episode_timeout_tics=self.spec.episode_timeout_tics)
        self.policy = policy_for(args, self.spec.game_id, agent_factory=lambda: VizDoomGameAgent(
            game_id=self.spec.game_id,
            model_profile_id="qwen3.5-player1-control-v-a-baserl",
        ))
        reset_policy(self.policy, args, job, self.spec.instruction)

    async def start(self):
        return self.env.start()

    async def step(self, action):
        from player1.environments.vizdoom.actions import map_policy_action
        mapped = map_policy_action(action, self.spec)
        if not mapped.valid:
            raise ValueError(f"Action is not executable on {self.spec.map_id}: {mapped.invalid_reason}")
        return self.env.step(mapped.action)

    def score(self, current):
        from player1.environments.vizdoom.scores import MAP_RETURN_SCALES
        return float(current.info["total_reward"]) / MAP_RETURN_SCALES[self.spec.map_id]

    async def close(self):
        self.env.close()
