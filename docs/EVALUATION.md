# Evaluation

Use an existing [model endpoint](MODELS.md). Edit model, revision, endpoint, and run settings in the corresponding example; run from the repository root.

| Benchmark                | Tasks × trials | Example                                                               | Metric                 |
| :----------------------- | :------------- | :-------------------------------------------------------------------- | :--------------------- |
| Player-1-Gym (in-domain) | 16 × 32        | [evaluate_gym.py](../examples/evaluation/evaluate_gym.py)             | Return per game        |
| MineDojo-300             | 300 × 8        | [evaluate_minedojo.py](../examples/evaluation/evaluate_minedojo.py)   | Task success           |
| ViZDoom-10               | 10 × 50        | [evaluate_vizdoom.py](../examples/evaluation/evaluate_vizdoom.py)     | Mean scaled return     |
| GameWorld                | 170 × 3        | [evaluate_gameworld.py](../examples/evaluation/evaluate_gameworld.py) | Task progress, success |

Examples select small checks. Remove their `tasks`, `trials`, and `max_steps` overrides for the full protocols. Matching runs resume completed episodes and retry failures; use a new output directory when changing the model or protocol.

---

## Gym, ViZDoom and GameWorld

```bash
python -m pip install -r requirements/gym.txt
python -m playwright install chromium
PYTHONPATH=. python examples/evaluation/evaluate_gym.py

python -m pip install -r requirements/vizdoom.txt
PYTHONPATH=. python examples/evaluation/evaluate_vizdoom.py
```

For GameWorld, obtain [GameWorld-Games](https://github.com/gameworld-project/GameWorld-Games) and set `GAMES_ROOT` to its `benchmark` directory:

```bash
PYTHONPATH=. python examples/evaluation/evaluate_gameworld.py
```

ViZDoom scales each map's mean return, then averages maps equally. Its ten maps keep seed slots `0–7, 10, 11`. Gym returns should be compared within each game.

---

## Minecraft

Use **Linux, Python 3.11, Java 8, and Xvfb**. MineDojo runs on Minecraft 1.16.5 with the MineStudio low-level runtime:

```bash
python -m pip install -r requirements/minecraft.txt
git clone https://github.com/CraftJarvis/MineStudio.git downloads/MineStudio
python scripts/evaluation/prepare_minecraft_runtime.py
python scripts/evaluation/download_minecraft_engine.py
export PYTHONPATH="$PWD:$PWD/downloads/minestudio-runtime${PYTHONPATH:+:$PYTHONPATH}"
export JAVA_HOME=/path/to/jdk8
export JAVA="$JAVA_HOME/bin/java"
export PATH="$JAVA_HOME/bin:$PATH"
export MINESTUDIO_DIR="$PWD/downloads/minecraft-runtime"
```

Build the engine patches once:

```bash
bash scripts/evaluation/build_minecraft_engine.sh \
  "$MINESTUDIO_DIR/engine/build/libs/mcprec-6.13.jar" \
  "$MINESTUDIO_DIR/engine/build/libs/mcprec-playerone.jar"
mv "$MINESTUDIO_DIR/engine/build/libs/mcprec-6.13.jar" \
  "$MINESTUDIO_DIR/engine/build/libs/mcprec-original.jar"
mv "$MINESTUDIO_DIR/engine/build/libs/mcprec-playerone.jar" \
  "$MINESTUDIO_DIR/engine/build/libs/mcprec-6.13.jar"
xvfb-run -a python examples/evaluation/evaluate_minedojo.py
```

Set `WORKERS` and `RUNTIME.minecraft_max_rollouts_per_jvm` in the example for available resources. Workers retain JVM reuse and result recovery. For isolated worker groups, configure `MinecraftControlGroupConfig` in [execution.py](../player1/evaluation/minestudio/execution.py).

The task loader also exposes these frozen selections; the evaluation entrypoint uses `minedojo-300`:

| Suite | Tasks | Trials/task |
| --- | ---: | ---: |
| `minedojo-full` | 1,581 | 3 |
| `minedojo-300` | 300 | 8 |

---

## Trajectory Viewer

All four benchmarks save compatible traces, screenshots, and results. Open one or more output directories containing `plan.json`:

```bash
conda run -n verl python -m player1.evaluation.viewer outputs/gym outputs/minedojo outputs/vizdoom outputs/gameworld
```

Open **http://127.0.0.1:8765** for episode/attempt selection, step playback, screenshots, actions, model outputs, and scores.

Keep each output directory complete (`plan.json`, `summary.json`, episode results, and `attempt-*` traces/frames). Copy it locally or forward port 8765 for remote runs. `EvaluationConfig.frame_interval=1` saves every policy observation and the final frame.

See [component sources](SOURCES.md) for upstream projects and asset notices.
