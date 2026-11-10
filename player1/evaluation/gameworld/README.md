<p align="center">
  <img src="docs/assets/gameworld-banner.jpeg" alt="GameWorld Banner">
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2604.07429">[Technical Report]</a> •
  <a href="https://gameworld-project.github.io/">[Project Page]</a> •
  <a href="docs/install/QUICK_START.md">[Quick Start]</a> •
  <a href="https://discord.com/invite/Qp8X6kVZSn">[Discord]</a>
</p>

**GameWorld** benchmarks multimodal game agents across 34 games and 170 tasks in a browser-based environment, using outcome-based, state-verifiable evaluation.


<table>
<tr>
  <th><strong>Puzzle</strong></th>
  <th><strong>Platformer</strong></th>
  <th><strong>Simulation</strong></th>
  <th><strong>Arcade</strong></th>
  <th><strong>Runner</strong></th>
</tr>
<tr>
  <td><img src="docs/assets/gifs/astray.gif" alt="Astray preview" width="140"/></td>
  <td><img src="docs/assets/gifs/captain-callisto.gif" alt="Captain Callisto preview" width="140"/></td>
  <td><img src="docs/assets/gifs/monkey-mart.gif" alt="Monkey Mart preview" width="140"/></td>
  <td><img src="docs/assets/gifs/pacman.gif" alt="Pac-Man preview" width="140"/></td>
  <td><img src="docs/assets/gifs/temple-run-2.gif" alt="Temple Run 2 preview" width="140"/></td>
</tr>
</table>

## 📢 Updates
- 2026.08: Released the new **Fine-Control Protocol** (branch: `fine-control-2026-08`) for higher-frequency, unified interaction with 400-step episodes. The finer control granularity better reveals models’ decision-making capabilities.
- 2026.06 GameWorld was used as a unified digital agent benchmark in <a href="https://lf3-static.bytednsdoc.com/obj/eden-cn/lapzild-tss/ljhwZthlaukjlkulzlp/seed2.1/Seed2_1_Model_Card.pdf" target="_blank" rel="noopener noreferrer">Seed-2.1 Model Card</a>. </li>
- 2026.06: GameWorld was accepted to **ECCV 2026**.
- 2026.04: The full game library for benchmarking is available at [gameworld-project/GameWorld-Games](https://github.com/gameworld-project/GameWorld-Games).
- 2026.04: GameWorld launched with its [Technical Report](https://arxiv.org/abs/2604.07429) and [Project Page](https://gameworld-project.github.io/).

## 📦 Installation

Python and browser environment:
```bash
conda create -n gameworld python=3.12
conda activate gameworld
pip install -r requirements.txt
playwright install chromium
```

Set the API keys for the providers you plan to use:
```bash
export GOOGLE_API_KEY=...
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

Or host your own models locally with `vLLM`.
```bash
vllm serve Qwen/Qwen3.5-122B-A10B --port 8088
```

Clone the full game library from at [gameworld-project/GameWorld-Games](https://github.com/gameworld-project/GameWorld-Games).

```bash
git clone https://github.com/gameworld-project/GameWorld-Games.git games/gameworld-games
```

More setup notes: [docs/install/INSTALLATION.md](docs/install/INSTALLATION.md).

## 🚀 Quick Start

First, validate that the browser and runtime are set up correctly:

```bash
python play.py --game 10_doodle-jump
```

Run a single preset:

```bash
python main.py --config 10_doodle-jump+10_01+gpt-5.2 --headed
```

Run a benchmark experiment:

```bash
python run_benchmark.py --experiment benchmark/experiments/quick-start.yaml --max-parallel 5
```

## 🖥️ Results and Monitoring

Results are saved to `results/run_<session>_<game>_<task>_<model>/`. The
canonical run data is stored in `run_meta.json`,
`agent_N/interactions.jsonl`, and `agent_0/evaluation/evaluation.json`.

We recommend using the dashboard to monitor the parallel runs. To launch the dashboard, run:

```bash
python -m tools.monitor.server --results-dir results --host 127.0.0.1 --port 8787 --open-browser
```

MP4 export is an explicit offline operation:

```bash
python tools/export_video.py --logs-dir results --session <run_id>
```

## 📚 Documentation

See [docs/](docs) for full documentation.

## 💬 Game Agent Community

🎙️ Join our [Discord](https://discord.com/invite/Qp8X6kVZSn) to discuss GameWorld, ask questions, and share your thoughts on multimodal game agents. GLHF!

## 📆 TODO

- [ ] Release GameWorld leaderboard.

## 📖 BibTeX
If you find GameWorld useful for your research, please kindly cite:
```bibtex
@article{ouyang2026gameworld,
  title={GameWorld: Towards Standardized and Verifiable Evaluation of Multimodal Game Agents},
  author={Ouyang, Mingyu and Hu, Siyuan and Lin, Kevin Qinghong and Ng, Hwee Tou and Shou, Mike Zheng},
  journal={arXiv preprint arXiv:2604.07429},
  year={2026},
}
```
