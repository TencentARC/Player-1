# Component sources

| Component | Source / version |
| --- | --- |
| Training engine | [verl v0.9.0](https://github.com/verl-project/verl) · [integration patches](../verl/PATCHES.md) |
| Gym and browser | Sixteen environments in `player1/gym`; Playwright Chromium matching the installed package |
| Bundled art and rendering | Three.js r185 (MIT) and game asset packs, including Kenney; source/license notices accompany the files |
| ViZDoom | Python engine 1.3.0; scenario notices are bundled with the assets |
| MineDojo tasks | Frozen Minecraft 1.16.5 port in `player1/evaluation/minestudio/minedojo_ported/data` |
| MineStudio | [CraftJarvis/MineStudio](https://github.com/CraftJarvis/MineStudio) |
| Minecraft engine | [SimulatorEngine](https://huggingface.co/CraftJarvis/SimulatorEngine), with the bundled Player-1 source patches |
| GameWorld | [Evaluator](https://github.com/gameworld-project/GameWorld), `fine-control-2026-08` task snapshot |
| GameWorld games | [GameWorld-Games](https://github.com/gameworld-project/GameWorld-Games), installed separately |

Retain bundled licenses and notices. External engines, recordings and game assets remain subject to their source terms; install their binaries separately.
