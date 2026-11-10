"""Episode-scoped history selection; never resample a generated PPO sample."""

from __future__ import annotations

import json
import random
from typing import Any


def episode_history_capacities(
    *, mode: str, recent: int | None, old: int | None, seed: int, episode: dict[str, Any]
) -> tuple[int | None, int | None]:
    if mode == "fixed":
        return recent, old
    if mode != "episode_uniform" or recent is None or old is None:
        raise ValueError("episode_uniform requires finite recent and old history capacities")
    if not episode.get("uid"):
        raise ValueError("episode_uniform requires the rollout uid")
    # Stable across format/trajectory retries, independent of async worker order
    # and action sampling. Store/replay the exact prompt, not a new random draw.
    identity = [seed, str(episode["uid"]), str(episode.get("session_id", "")), str(episode.get("global_steps", ""))]
    rng = random.Random(json.dumps(identity))
    return rng.randrange(recent + 1), rng.randrange(old + 1)
