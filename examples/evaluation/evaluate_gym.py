"""Evaluate Player-1-Gym and save a trajectory for the shared viewer."""

import asyncio
from pathlib import Path

from player1.evaluation.common import EvaluationConfig
from player1.evaluation.gym import evaluate

CONFIG = EvaluationConfig(
    model="Player-1-9B",
    model_revision="YOUR_CHECKPOINT_REVISION",
    endpoint="http://127.0.0.1:8000/v1",
    output=Path("outputs/gym"),
)


if __name__ == "__main__":
    print(asyncio.run(evaluate(CONFIG, tasks=["base_3d_aim"], trials=1, max_steps=10)))
