# Catalog

The catalog owns games and tasks. A preset combines them with model ids from
`agents/mm_agents/` into a `RuntimeConfig`.

## Preset syntax

```bash
python main.py --config game_id+task_id+model1,model2
```

- `game_id`: exact game YAML stem
- `task_id`: exact task YAML stem under `catalog/tasks/<game_id>/`
- `model1,model2`: one model per role, or one shared model duplicated across roles

## Ownership

- Game YAML: rules, role definitions, controls, and semantic actions.
- Task YAML: prompt, objective, extra reported metrics, and optional URL suffix.
- Agent adapter: client, prompt/output contract, parser, and model definitions.

General prompts receive an action list generated from `semantic_controls`.

### Game YAML

Path: `catalog/games/**/*.yaml`

- `game_rules`
- `player_mode`
- `speed_multiplier`
- `width`, `height`
- `url`
- `game_roles`

`game_id` comes from the filename. `player_mode` defaults to `single` and
`speed_multiplier` to `1.0`. Each `game_roles[]` entry defines:

- `name`
- `prompt.role_section`
- `prompt.computer_use_controls_section`
- `computer_use_controls`
- optional `semantic_controls`

Minimal example:

```yaml
game_rules: |
  Merge tiles and maximize score.

game_roles:
  - name: player
    prompt:
      role_section: |
        You control the board.
      computer_use_controls_section: |
        ACTION SPACE:
        - Arrow keys
    computer_use_controls:
      allowed_keys: ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]
      allow_clicks: false
    semantic_controls:
      - id: move_up
        description: Slide up.
        binding: { action: press_key, key: "ArrowUp" }
```

Runtime accepts one primitive per step. `press_keys` is simultaneous; action lists
are rejected. Keyboard actions obey `allowed_keys`, `type` is limited to five
characters, durations are capped at two seconds, and mouse actions require
`allow_clicks: true`.

### Task YAML

Path: `catalog/tasks/<game_id>/<task_id>.yaml`

- `task_prompt`
- `game_url_suffix`
- `evaluator_config`

`game_id` and `task_id` come from the path.

Evaluator notes:

- Runtime policy is fixed: 400 steps, pause during inference, and reset-and-continue
  after terminal failure.
- `objective.reach` defines numeric targets. Scalars start at `0`; use
  `{start: ..., target: ...}` for another baseline.
- `objective.require` defines exact intrinsic state requirements.
- All targets and requirements are conjunctive. Target progress is independently
  capped, then averaged.
- `metrics_fields` adds report fields without changing progress.
- `fail` and `aborted` override same-snapshot target attainment. With an objective,
  terminal success alone is insufficient.
- Terminal outcomes are `success`, `fail`, `aborted`, or `unknown`.

Minimal example:

```yaml
task_prompt: |
  Reach at least 128.
evaluator_config:
  objective:
    reach:
      metrics.max_tile: 128
```

Each target's progress is `(best - start) / (target - start)`, clamped to `[0, 1]`.

### Model YAML

Path: `agents/mm_agents/<adapter_id>/models.yaml`

Each key is a benchmark-facing model id. `enable_memory` is runtime metadata; other
fields override the adapter's config. The parent package owns behavior and prompts.

Minimal example:

```yaml
gpt-5.2:
  model: "gpt-5.2"
  enable_memory: true
```

## Prompt assembly

Prompt rendering uses the selected model's adapter contract plus:

- shared `game_rules`
- the role's prompt section
- the task prompt
- the adapter-owned output format
