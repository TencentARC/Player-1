# Benchmark Experiments

Experiment YAMLs under `benchmark/experiments/` expand into benchmark runs.

## Quick start

```bash
python run_benchmark.py --experiment benchmark/experiments/quick-start.yaml --max-parallel 5
```

## Experiment YAML

```yaml
experiment_name: qwen3.5-35b-a3b_all_games_all_tasks
headless: true

cases:
  - game: all
    tasks: all
    models: ["qwen3.5-35b-a3b"]
    repeat: 1
```

Each case requires `game`, `tasks`, and `models`:

- `game: all` with `tasks: all` selects the full catalog.
- A specific game may use `tasks: all` or an explicit task list.
- `models: all` selects every registered model; explicit models use a list.
- One model is duplicated across roles for multi-role games.
- `repeat: N` creates repeat waves.
- Quote explicit ids with leading zeros.

`headless` is the only experiment-level runtime override.

## CLI

- `--experiment <path>`
- `--max-parallel N`
- `--port N`: base game server port; run `i` uses `N + i - 1`
- `--results-dir <path>`: defaults to `results`
- `--model-endpoint <url>`: override endpoints; repeat for a round-robin pool to improve test throughput

For four local model replicas with five concurrent runs:

```bash
python run_benchmark.py \
  --experiment benchmark/experiments/qwen3.5-35b-a3b.yaml \
  --max-parallel 5 \
  --model-endpoint http://127.0.0.1:8004/v1/chat/completions \
  --model-endpoint http://127.0.0.1:8005/v1/chat/completions \
  --model-endpoint http://127.0.0.1:8006/v1/chat/completions \
  --model-endpoint http://127.0.0.1:8007/v1/chat/completions
```

## Output

Each benchmark writes to `results/<experiment_name>_<timestamp>/`.
Run and experiment directories are single-owner artifacts; an existing output
directory is rejected instead of resumed or appended.

Main files:

- `summary.json`: experiment-level metadata and aggregates
- `runs.csv`: per-run status and artifact paths
- `aggregate_by_model.csv`: model-level aggregation
- `runs/run_XXX_.../stderr.log`: subprocess stderr/stdout log

Each run keeps canonical metadata, interaction history, and one task snapshot:

- `run_meta.json`
- `agent_N/interactions.jsonl`
- `agent_0/evaluation/evaluation.json`

The evaluation is eligible for completed-run aggregation only when `finalized`
is `true`. See [tools/MONITOR.md](tools/MONITOR.md) for dashboard inspection and
explicit offline video export.
