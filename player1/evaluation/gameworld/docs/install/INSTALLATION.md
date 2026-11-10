# Installation

## Requirements

- Python 3.12 recommended
- Chromium via Playwright
- `ffmpeg` only if you want to run the optional MP4 exporter
- API keys for any cloud providers you plan to use
- Local vLLM-hosted models, if you run local profiles

## Python and Browser Environment

```bash
conda create -n gameworld python=3.12
conda activate gameworld
pip install -r requirements.txt
playwright install chromium
```

On Linux, install the Chromium system dependencies as well:

```bash
playwright install-deps chromium
```

Playwright fallback notes are in [PLAYWRIGHT.md](PLAYWRIGHT.md).

## Provider Keys

Set only the provider keys needed by the model profiles you plan to run:

```bash
export GOOGLE_API_KEY=...
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export ZAI_API_KEY=...
export XAI_API_KEY=...
export ARK_API_KEY=...
```

## Local Models

Or host your own models locally with `vLLM`:

```bash
pip install vllm
vllm serve Qwen/Qwen3.5-122B-A10B --port 8088
```

## Game Library

Clone the game repository. `GameLauncher` discovers its inner `benchmark` directory:

```bash
git clone https://github.com/gameworld-project/GameWorld-Games.git games/gameworld-games
```

After installation, validate the browser runtime with Doodle Jump:

```bash
python play.py --game 10_doodle-jump
```
