"""Run a seeded environment and save its initial and post-action screenshots."""

import asyncio
from pathlib import Path

from player1.gym import GymEnv


async def main():
    output = Path("outputs/gym-example")
    output.mkdir(parents=True, exist_ok=True)
    async with GymEnv("base_3d_aim") as env:
        observation = await env.reset(seed=42)
        observation.image.save(output / "initial.png")
        observation = await env.step({
            "type": "game_step_action", "id": "control", "duration_ms": 200,
            "mouse": {"mode": "relative", "dx": 50, "dy": -20},
            "mouse_click": {"button": "left"},
        })
        observation.image.save(output / "after.png")
        print({"reward": observation.reward, "terminated": observation.terminated})


if __name__ == "__main__":
    asyncio.run(main())
