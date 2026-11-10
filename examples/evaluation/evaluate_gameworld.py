"""Run a small GameWorld evaluation against an existing model endpoint."""

import asyncio
from pathlib import Path

from player1.evaluation.common import EvaluationConfig
from player1.evaluation.gameworld.evaluate import evaluate

CONFIG = EvaluationConfig(
    model="Player-1-9B",
    model_revision="YOUR_CHECKPOINT_REVISION",
    endpoint="http://127.0.0.1:8000/v1",
    output=Path("outputs/gameworld"),
)
GAMES_ROOT = Path("downloads/GameWorld-Games/benchmark")


if __name__ == "__main__":
    print(asyncio.run(evaluate(CONFIG, games_root=GAMES_ROOT, tasks=["01_01"], trials=1, max_steps=8)))
