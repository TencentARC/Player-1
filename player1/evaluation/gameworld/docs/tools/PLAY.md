# Play Tool

`play.py` is the lightweight game-integration tool. Use it to inspect `window.gameAPI` and validate one game/task without running the full agent loop.

## Commands

### Stream state

```bash
python play.py --game 01_2048
python play.py stream-state --game 01_2048 --headless
```

- If you omit the subcommand, `play.py` defaults to `stream-state`.
- The command launches the catalog game and prints `gameAPI.getState()` summaries once per second.
- `--suffix` appends a URL suffix after the base game URL.

### Capture task

```bash
python play.py capture-task --game 01_2048 --task 01_01 --headless
```

- Loads the catalog game and task.
- Waits for an actionable lifecycle state.
- Evaluates the task once against the current `gameAPI` snapshot.
- If the evaluator requests reset, it also exercises `gameAPI.reset()` and evaluates again.

## Output

`capture-task` writes to:

`results/play/<game_id>/<task_id>/`

Files:

- `capture.png`: latest screenshot
- `manifest.json`: task prompt, resolved game URL, state summary, full state payload, and task evaluation

## Common flags

- `--game`: exact catalog game id
- `--task`: exact task id for `capture-task`
- `--port`: local HTTP port, default `8101`
- `--headless`: run Chromium headless
- `--suffix`: URL suffix override

## When to use it

- Validate a new or migrated `window.gameAPI`
- Check lifecycle states such as `loading`, `ready`, `playing`, and `terminal`
- Confirm task evaluator wiring before running `main.py`
- Capture a reproducible screenshot and state manifest for debugging
