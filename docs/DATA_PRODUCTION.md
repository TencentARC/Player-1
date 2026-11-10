# Producing Player-1-Data

Create annotated datasets from recordings: **prepare actions/screenshots → game profile → task → per-turn reasoning → dataset**. Recorded actions stay fixed. See Appendix B of the [paper](https://arxiv.org/abs/2610.20584).

## Install

Use Python 3.11+ with FFmpeg and ffprobe on PATH:

```bash
python -m pip install -r requirements/data.txt
# For D2E recordings:
python -m pip install -r requirements/data-mcap.txt
```

## Configure

Copy an [ordinary](../examples/data/ordinary/recipe.json) or [GUI](../examples/data/gui/recipe.json) recipe. Paths resolve relative to the recipe. Set each recording's `source`, `input`, game name/version, mode and `count`. Optional `source_revision` records the input version; it defaults to `local`.

| Source | Input |
| --- | --- |
| `vpt` | Contractor JSONL and same-stem MP4 |
| `pixel2play` | Directory with `annotation.proto` and `video.mp4`; gameplay mode |
| `gaming500` | Directory with `clip.mp4`, `frame_events.json`, `metadata.json` |
| `d2e` | MCAP/video, explicit `source_root` and reviewed `session_allowlist` |

## Annotate and export

Use an OpenAI-compatible vision provider accepting inline JPEGs and JSON responses. It must support a whole-trajectory storyboard. Set credentials in the environment:

```bash
export PLAYER1_DATA_ENDPOINT=http://127.0.0.1:8000/v1
export PLAYER1_DATA_MODEL=your-vision-model
export PLAYER1_DATA_API_KEY=your-key-if-required
python -m player1_data run --config recipe.json --work ./work --output ./dataset
```

`split_seed` and `validation_basis_points` control source-session splits; zero basis points gives train-only output. The final directory follows the [data format](DATA.md).


## View

```bash
python -m player1_data view ./dataset --port 8765
tar -czf dataset.tar.gz dataset
```

Open the printed URL to inspect instructions, screenshots, reasoning and actions. Check upstream redistribution terms for recordings and screenshots.

Sources: [Gaming500](https://huggingface.co/datasets/markov-ai/gaming-500-hours), [D2E-Original](https://huggingface.co/datasets/open-world-agents/D2E-Original), [Pixel2Play](https://huggingface.co/datasets/elefantai/p2p-full-data), [VPT](https://github.com/openai/Video-Pre-Training).
