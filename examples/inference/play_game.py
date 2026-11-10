"""Let the model control a Gym environment for a short episode."""

import asyncio

from player1.agents.inference import AgentConfig, GameAgent, ModelConfig, PlayerOnePolicy
from player1.agents.vision import prepare_agent_image
from player1.gym import GymEnv

GAME = "base_3d_aim"
MODEL = "Player-1-9B"
ENDPOINT = "http://127.0.0.1:8000/v1"
STEPS = 10


async def main():
    policy = PlayerOnePolicy(
        ModelConfig(model=MODEL, endpoint=ENDPOINT, max_tokens=512, enable_thinking=True),
        agent_factory=lambda: GameAgent(AgentConfig(
            game_id=GAME, model_profile_id="qwen3.5-player1-control-v-a-baserl",
        )), action_format_retry_max=0,
    )
    policy.reset("Aim at the active target and fire.", seed=42,
                 context={"max_decisions": STEPS, "history_context_turns": 2})
    async with GymEnv(GAME) as env:
        observation = await env.reset(seed=42)
        for _ in range(STEPS):
            image = prepare_agent_image(observation.image, max_height=480)
            step = await asyncio.to_thread(policy.act, image)
            observation = await env.step(step.control_action)
            policy.commit_after_successful_step(step, observation)
            print({"valid": step.valid, "action": step.control_action, "reward": observation.reward})
            if observation.terminated or observation.truncated:
                break


if __name__ == "__main__":
    asyncio.run(main())
