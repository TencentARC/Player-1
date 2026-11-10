# Upstream GameWorld

This directory vendors the public GameWorld runtime from:

- Repository: `https://github.com/gameworld-project/GameWorld`
- Branch: `fine-control-2026-08`
- Revision: `033115f6275832b470e59d24c228db152c84ddd3`
- Commit date: `2026-08-25T16:01:50+08:00`
- Upstream subject: `Add Qwen3.5 9B model preset`

This snapshot uses the Fine-Control Protocol: 400 agent steps per task and
the game-specific action durations recorded in the upstream catalog. The
upstream `.git` directory is intentionally not vendored. GameGym-specific
files use a `game_gym_` prefix, including the isolated trained-model agent in
`game_gym_agent.py`. The reviewed local additions and the three modified
upstream files (`.gitignore`, `env/browser_manager.py`, and `runtime/env.py`)
are recorded in
[`docs/maintenance/GAMEWORLD_PATCH_MANIFEST.md`](../../../docs/maintenance/GAMEWORLD_PATCH_MANIFEST.md).
That manifest is the authoritative rebase inventory for this snapshot.

Upstream records `games/gameworld-games` as a gitlink at
`a23b4370c3f99df6fa4ee01ea0299fdab9668b86` without a `.gitmodules` mapping.
GameGym keeps that directory out of source snapshots and uses
`scripts/game_gym/evaluation/gameworld/setup_games.sh` to install or update the
current `GameWorld-Games` `main` branch when a full evaluation starts.

The upstream repository does not include a standalone license file at this
revision. Its original README and source notices are preserved verbatim.
