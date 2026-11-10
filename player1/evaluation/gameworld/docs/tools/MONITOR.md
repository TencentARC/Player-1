# Monitor

The runtime exposes two lightweight views over the canonical run artifacts:

- concise benchmark progress events written by `run_benchmark.py`
- the HTTP dashboard served by `tools.monitor.server`

## Benchmark progress

Benchmark output reports run starts and completions without maintaining a
multi-line terminal UI. Final experiment aggregation accepts
`agent_0/evaluation/evaluation.json` only when `finalized` is `true`.

## Dashboard server

```bash
python -m tools.monitor.server --results-dir results --host 127.0.0.1 --port 8787 --open-browser
```

The dashboard provides a bounded run overview and an interaction timeline for a
selected run. It reads:

- `run_meta.json`
- `experiment_manifest.json`
- `agent_0/evaluation/evaluation.json`
- `agent_N/interactions.jsonl`
- image artifacts referenced by interaction records

The HTTP API is intentionally small:

- `GET /api/overview` returns active runs plus enough recent runs to reach the
  configured limit
- `GET /api/experiments/<experiment_id>` returns one experiment
- `GET /api/runs/<run_id>` returns one standalone run snapshot
- `GET /api/experiments/<experiment_id>/runs/<run_id>` returns one experiment
  run snapshot

Only canonical run and experiment directories are visible. Lookup is
deterministic:

- `experiment_id` resolves to `results/<experiment_id>/`
- standalone `run_id` resolves to `results/<run_id>/`
- experiment runs resolve through
  `results/<experiment_id>/runs/<run_id>/`

`/artifacts/<file>` serves only canonical screenshot or memory images and each
run's `stderr.log`. It provides no directory browsing and does not serve HTML,
JSON, or MP4 files. `run_meta.json` stores `stderr.log` as a run-relative path.
Directories without canonical metadata are ignored; missing interactions or
evaluations are surfaced as empty or incomplete runs.

## Canonical data

`interactions.jsonl` is the single interaction history. Each record must contain
its canonical `agent_id` and logged image paths.

An incomplete final JSONL record may be ignored only while a run is active.
Malformed completed logs are errors.

## Optional video export

Video creation is an explicit offline command and is never run by `main.py`:

```bash
python tools/export_video.py \
  --logs-dir results \
  --session run_20260413_120000_01_2048_01_01_gpt-5.2 \
  --fps 6 \
  --render-mode with_ui_overlay
```

For an experiment run, point `--logs-dir` at
`results/<experiment_id>/runs`. Use `--render-mode raw_screenshots` to omit
keyboard, mouse, and action overlays. The default output is written inside the
selected run directory.

The exporter requires `ffmpeg` and reads the same canonical
`interactions.jsonl` and screenshot paths as the dashboard. Both `--logs-dir`
and `--session` are required.
