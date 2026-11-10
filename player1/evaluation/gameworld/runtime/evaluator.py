"""Task evaluation wrapper for runtime loops."""

from __future__ import annotations

from typing import Any

from env import build_task_evaluator, reset_task_evaluator_episode_metrics

from .runtime_config import RuntimeConfig
from .game_agent import Agent


class Evaluator:
    """Task evaluator that consumes game-state snapshots."""

    def __init__(self, config: RuntimeConfig):
        self.task_evaluator = build_task_evaluator(
            evaluator_config=config.evaluator_config,
            max_steps=config.max_steps,
        )

    async def _run(
        self,
        agent: Agent,
        state: dict[str, Any] | None,
    ):
        result = await self.task_evaluator(
            state=state,
            step_index=agent.step_index,
            metrics=agent.eval_metrics,
        )
        agent.eval_metrics = dict(result.metrics)
        return result

    async def evaluate(self, agent: Agent, state: dict[str, Any] | None):
        return await self._run(agent, state)

    def reset_metrics(self, metrics: dict[str, Any] | None) -> dict[str, Any]:
        return reset_task_evaluator_episode_metrics(metrics)


__all__ = ["Evaluator"]
