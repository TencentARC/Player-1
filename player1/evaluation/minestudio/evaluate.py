"""MineDojo task selection, Minecraft adapter and evaluation entrypoint."""

import asyncio
from dataclasses import replace
from functools import partial

from ..common import (
    policy_for,
    prepare_evaluation,
    reset_policy,
    run_episode,
    run_episodes,
    summarize,
    write_json,
)
from .execution import (
    DEFAULT_MINECRAFT_EVALUATION_WORKERS,
    OfficialRuntimeConfig,
    close_worker_minecraft_simulators,
    isolated_minecraft_runtime,
    run_trial_batch,
)

BENCHMARK = "minedojo"


def build_episodes(*, tasks=(), trials=8, max_steps=None):
    from .minedojo_ported.manifest import load_compiled_manifest
    from .minedojo_ported.suites import load_minedojo_ported_suite
    from .minedojo_ported.trials import materialize_minedojo_ported_trials
    if trials <= 0 or max_steps is not None and max_steps <= 0:
        raise ValueError("Trial count and max steps must be positive")
    suite = load_minedojo_ported_suite("minedojo-300")
    selected = set(tasks) if tasks else set(suite.task_ids)
    if selected - set(suite.task_ids):
        raise ValueError(f"Unknown MineDojo tasks: {selected - set(suite.task_ids)}")
    rows = []
    for trial in materialize_minedojo_ported_trials(
        load_compiled_manifest(), task_ids=tuple(task for task in suite.task_ids if task in selected),
        trials_per_task=trials, max_decisions=max_steps or 1000,
    ):
        trial = replace(trial, selection_suite_id=suite.suite_id)
        rows.append({"task_id": trial.task_id, "trial": trial.trial_index, "seed": trial.task_rng_seed,
                     "max_steps": trial.max_decisions, "payload": trial.to_dict()})
    for row in rows:
        row["benchmark"] = BENCHMARK
        row["episode_id"] = f"{BENCHMARK}/{row['task_id']}/trial-{row['trial']:04d}"
    return rows


def _run_trial(payload):
    job, (config, signature, runtime) = payload
    return asyncio.run(run_episode(config, job, partial(_Episode, runtime_config=runtime), signature))


async def evaluate(
    config, *, tasks=(), trials=8, max_steps=None,
    workers=DEFAULT_MINECRAFT_EVALUATION_WORKERS, runtime=None,
):
    if workers <= 0:
        raise ValueError("MineDojo worker count must be positive")
    runtime = runtime or OfficialRuntimeConfig()
    groups = runtime.minecraft_control_groups
    if groups is not None and workers != groups.worker_capacity:
        raise ValueError("MineDojo workers must fill the configured control-group capacity")
    episodes = build_episodes(tasks=tasks, trials=trials, max_steps=max_steps)
    if workers == 1 and groups is None:
        try:
            return await run_episodes(config, episodes, partial(_Episode, runtime_config=runtime))
        finally:
            close_worker_minecraft_simulators()
    signature = prepare_evaluation(config, episodes)
    completed = []

    def record_result(result):
        completed.append(result)
        write_json(config.output / "summary.json", summarize(episodes, completed))

    results = await asyncio.to_thread(
        run_trial_batch, episodes, (config, signature, runtime),
        worker=_run_trial, workers=workers, minecraft_control_groups=groups, on_result=record_result,
    )
    summary = summarize(episodes, results)
    write_json(config.output / "summary.json", summary)
    return summary


class _Episode:
    def __init__(self, args, job, *, runtime_config=None):
        from .minedojo_ported.official_env import MineDojoPortedEnvironment
        from .minedojo_ported.trials import MineDojoPortedTrial
        from .official_eval import OfficialActionAdapter
        self.env = MineDojoPortedEnvironment(
            MineDojoPortedTrial(**job["payload"]),
            runtime_config=isolated_minecraft_runtime(runtime_config or OfficialRuntimeConfig()),
            render_size=(864, 480), agent_image_short_edge=480,
            action_adapter=OfficialActionAdapter(visible_game_size=(864, 480)),
        )
        from .agent import MineStudioGameAgent
        from player1.agents.inference import AgentConfig
        self.policy = policy_for(args, "minecraft_minestudio", agent_factory=lambda: MineStudioGameAgent(
            AgentConfig(model_profile_id="qwen3.5-player1-control-v-a-baserl"),
        ))
        reset_policy(self.policy, args, job, job["payload"]["instruction"])

    async def start(self):
        return self.env.start()

    async def step(self, action):
        return self.env.step(action)

    def score(self, current):
        return float(current.evaluation.success)

    async def close(self):
        self.env.close()
