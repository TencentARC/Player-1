"""Request one native Player-1 action from an existing model endpoint."""

import json
from pathlib import Path

from PIL import Image

from player1.agents.inference import AgentConfig, GameAgent, ModelConfig, PlayerOnePolicy
from player1.agents.vision import prepare_agent_image

IMAGE_PATH = Path("/path/to/observation.png")
MODEL = "Player-1-9B"
ENDPOINT = "http://127.0.0.1:8000/v1"


def main():
    policy = PlayerOnePolicy(
        ModelConfig(model=MODEL, endpoint=ENDPOINT, max_tokens=512, enable_thinking=True),
        agent_factory=lambda: GameAgent(AgentConfig(
            game_id="base_3d_aim", model_profile_id="qwen3.5-player1-control-v-a-baserl",
        )),
    )
    policy.reset("Aim at the active target and shoot.", seed=42, context={"max_decisions": 1})
    with Image.open(IMAGE_PATH) as image:
        step = policy.act(prepare_agent_image(image, max_height=480))
    print(json.dumps({"action": step.control_action, "valid": step.valid}, indent=2))


if __name__ == "__main__":
    main()
