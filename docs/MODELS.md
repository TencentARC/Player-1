# Model inference

Player-1 policies run on OpenAI-compatible vision endpoints. Official checkpoints are available on Hugging Face: [Player-1-9B](https://huggingface.co/yyyang/Player-1-9B) and [Player-1-35B-A3B](https://huggingface.co/yyyang/Player-1-35B-A3B), or you can use your own [SFT/RL export](TRAINING.md#checkpoints-and-sft-to-rl).

---

## Setup

```bash
python -m pip install -r requirements/gym.txt
python -m playwright install chromium
```

With a local HF export and a vLLM version supporting Qwen3.5:

```bash
vllm serve /path/to/model --served-model-name Player-1-9B --port 8000 \
  --chat-template player1/agents/chat_template/qwen3_5_player1_full_history.jinja \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3
```

---

## Run

Set the model, endpoint, and input path at the top of each example, then run from the repository root:

```bash
PYTHONPATH=. python examples/inference/single_image.py
PYTHONPATH=. python examples/inference/play_game.py
```

The first requests an action for one screenshot; the second runs the policy in Gym. For authenticated endpoints, set `ModelConfig.api_key_env` to the environment variable holding the key.
