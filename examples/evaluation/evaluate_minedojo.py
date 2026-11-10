"""Run a small MineDojo evaluation against an existing model endpoint."""

import asyncio
from pathlib import Path

from player1.evaluation.common import EvaluationConfig
from player1.evaluation.minestudio.evaluate import evaluate
from player1.evaluation.minestudio.execution import OfficialRuntimeConfig

CONFIG = EvaluationConfig(
    model="Player-1-9B",
    model_revision="YOUR_CHECKPOINT_REVISION",
    endpoint="http://127.0.0.1:8000/v1",
    output=Path("outputs/minedojo"),
)
WORKERS = 8
RUNTIME = OfficialRuntimeConfig(minecraft_max_rollouts_per_jvm=8)


if __name__ == "__main__":
    print(asyncio.run(evaluate(
        CONFIG, tasks=["combat_chicken_plains_barehand"], trials=1, max_steps=8,
        workers=WORKERS, runtime=RUNTIME,
    )))
