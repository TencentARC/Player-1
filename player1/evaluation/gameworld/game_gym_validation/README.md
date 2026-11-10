# GameGym Prompt Profiles

This directory owns the Agent-visible prompt profiles used when GameGym evaluates
the vendored GameWorld benchmark. It does not modify GameWorld's original catalog,
which remains available to upstream agents.

Every catalog game has one required file under `games/` with `profile: game-gym`. A profile contains:

- concise game mechanics without nested Markdown sections;
- role descriptions and controls that the loader renders as `Role:` and `Controls:`;
- exactly two ordered, named, contrasting examples per role and GameGym action-space mode.

The two examples describe different visible states and produce different actions.
Timing-sensitive games use one action example and one `wait` example so the prompt
teaches when to act, rather than merely demonstrating an action's wire format.
Each YAML item defines `name` and `response`; the shared GameGym renderer emits
`Example N - name:`. Profile files never hand-number or concatenate examples.
Reasoning stays as one state-grounded sentence, targeting roughly 24-32 tokens
under the maintained Qwen3.5 tokenizer.

The loader fails closed when a catalog game has no profile or its role names do not
match the original GameWorld catalog.
