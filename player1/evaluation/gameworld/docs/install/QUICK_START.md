# Quick Start

## 1) Installation

Follow [INSTALLATION.md](INSTALLATION.md).

## 2) Validate the Browser Runtime

```bash
python play.py --game 10_doodle-jump
```

`play.py` launches the game and prints `window.gameAPI.getState()` summaries once per second.

## 3) Run a Single Preset

```bash
python main.py --config 10_doodle-jump+10_01+gpt-5.2 --headed
```

Format: `game_id+task_id+model1,model2`.

- `game_id` must match a file stem under `catalog/games/`
- `task_id` must match a file stem under `catalog/tasks/<game_id>/`
- `model_id` must match a key declared in `agents/mm_agents/*/models.yaml`

If the game has multiple roles and you provide one model id, the runtime duplicates that model across roles.

## 4) Run a Benchmark Experiment

```bash
python run_benchmark.py --experiment benchmark/experiments/quick-start.yaml --max-parallel 5
```

## 5) Inspect Results

```bash
python -m tools.monitor.server --results-dir results --host 127.0.0.1 --port 8787 --open-browser
```
