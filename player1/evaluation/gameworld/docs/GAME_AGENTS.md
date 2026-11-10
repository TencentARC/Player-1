# Agents

`agents/mm_agents/` owns model clients, prompts, response parsing, and model variants.
Select a model with:

```bash
python main.py --config game_id+task_id+model_id
```

`model_id` must be a key in `agents/mm_agents/*/models.yaml`.

## Adapters

Each adapter package exports:

- `Client`: a `BaseClient` implementation
- `Config`: its `BaseClientConfig`
- `PROMPT_TEMPLATE`: a template under `agents/templates/`
- `OUTPUT_FORMAT`: model-specific output instructions, or `None`

`agents/mm_agents/loader.py` discovers model YAMLs and imports their parent adapter.
Shared runtime code lives in `base/`; compatible adapters may share a `*_common/`
package.

Keep separate adapters when prompt, parser, or action behavior differs. For example,
Qwen3.5/3.6 use function/parameter XML, while Qwen3-VL uses JSON inside `tool_call`.

## Add a variant

Add the model to the compatible adapter's `models.yaml`:

```yaml
qwen3.5-example:
  model: "Qwen/Qwen3.5-Example"
  endpoint: "http://127.0.0.1:8088/v1/chat/completions"
  enable_memory: true
```

The YAML key is the benchmark-facing id. Other fields override attributes on the
adapter's `Config`.

## Add an adapter

1. Add a package under `agents/mm_agents/` with the four exports above.
2. Keep its prompt in `prompt.py` and implementation/parser code beside it or in a
   compatible `*_common/` package.
3. Add `models.yaml` with at least one model id.

No catalog entry or model-specific experiment is required.
