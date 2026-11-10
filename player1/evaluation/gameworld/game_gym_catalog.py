"""GameGym-facing trial materialization owned by the vendored GameWorld tree.

This module intentionally imports only GameWorld modules and the Python
standard library.  The outer GameGym integration consumes its JSON output over
a subprocess boundary, so upstream GameWorld never depends on GameGym.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from catalog.games import list_games, load_game
from catalog.tasks import list_tasks, load_task
from game_gym_validation import GameGymPromptProfile, load_game_gym_prompt_profile


GAMEWORLD_170_SUITE = "gameworld-170-tasks"
GAMEWORLD_SUITES = (GAMEWORLD_170_SUITE,)
GAMEWORLD_BENCHMARK_RELEASE = "fine-control-2026-08"
GAMEWORLD_DEFAULT_MAX_STEPS = 400


def _all_tasks() -> list[tuple[str, str]]:
    return [
        (game_id, task_id)
        for game_id in list_games()
        for task_id in list_tasks(game_id)
    ]


def suite_tasks(suite_id: str) -> list[tuple[str, str]]:
    """Return stable ``(game_id, task_id)`` pairs for the 170-task benchmark."""

    normalized = str(suite_id or "").strip()
    if normalized == GAMEWORLD_170_SUITE:
        return _all_tasks()
    raise ValueError(
        f"Unknown GameWorld suite {suite_id!r}; expected {GAMEWORLD_170_SUITE!r}"
    )


def select_suite_tasks(suite_id: str, task_ids: Iterable[str] | None) -> list[tuple[str, str]]:
    """Select explicit task IDs from a suite while preserving request order."""

    available = suite_tasks(suite_id)
    requested = [str(task_id or "").strip() for task_id in (task_ids or [])]
    if not requested:
        return available
    if any(not task_id for task_id in requested):
        raise ValueError("GameWorld task IDs must be non-empty")
    if len(set(requested)) != len(requested):
        raise ValueError(f"GameWorld task selection contains duplicates: {requested!r}")

    pairs_by_task_id: dict[str, list[tuple[str, str]]] = {}
    for pair in available:
        pairs_by_task_id.setdefault(pair[1], []).append(pair)
    ambiguous = [task_id for task_id in requested if len(pairs_by_task_id.get(task_id, [])) > 1]
    if ambiguous:
        raise ValueError(f"GameWorld task IDs are ambiguous within {suite_id!r}: {ambiguous!r}")
    missing = [task_id for task_id in requested if task_id not in pairs_by_task_id]
    if missing:
        raise ValueError(f"GameWorld task IDs are not in suite {suite_id!r}: {missing!r}")
    return [pairs_by_task_id[task_id][0] for task_id in requested]


def _role_payload(role: Any, prompt_profile: GameGymPromptProfile) -> dict[str, Any]:
    controls = role.controls
    prompt = prompt_profile.roles[str(role.name)]
    return {
        "name": str(role.name),
        "allowed_keys": sorted(str(key) for key in controls.allowed_keys),
        "hold_duration": float(controls.hold_duration),
        "key_durations": {
            str(key): float(duration)
            for key, duration in sorted(controls.key_durations.items())
        },
        "allow_clicks": bool(controls.allow_clicks),
        "role_section": prompt.render_role_section(),
        "computer_use_controls_section": prompt.render_controls_section(),
        "in_context_examples": {
            mode: [{"name": example.name, "response": example.response} for example in examples]
            for mode, examples in prompt.in_context_examples.items()
        },
    }


def materialize_trial(
    game_id: str,
    task_id: str,
    *,
    trial_index: int,
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Serialize one deterministic GameWorld trial without model dependencies."""

    if isinstance(trial_index, bool) or not isinstance(trial_index, int) or trial_index < 0:
        raise ValueError("GameWorld trial_index must be a non-negative integer")
    if max_steps is not None and (
        isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0
    ):
        raise ValueError("GameWorld max_steps must be a positive integer when provided")

    game = load_game(game_id)
    task = load_task(game_id, task_id)
    prompt_profile = load_game_gym_prompt_profile(game_id)
    prompt_profile.require_roles({str(role.name) for role in game.game_roles})
    return {
        "protocol": "gameworld.game-gym.v1",
        "benchmark_release": GAMEWORLD_BENCHMARK_RELEASE,
        "suite_game_id": str(game.game_id),
        "game_id": str(game.game_id),
        "task_id": str(task.task_id),
        "trial_index": trial_index,
        "random_seed": trial_index,
        "max_steps": int(max_steps or GAMEWORLD_DEFAULT_MAX_STEPS),
        "game_url_suffix": task.game_url_suffix,
        "game_rules": prompt_profile.game_rules,
        "task_prompt": str(task.task_prompt).strip(),
        "evaluator_config": deepcopy(task.evaluator_config),
        "speed_multiplier": float(game.speed_multiplier),
        "width": int(game.width),
        "height": int(game.height),
        "url": game.url,
        "roles": [_role_payload(role, prompt_profile) for role in game.game_roles],
        "game_gym_prompt_profile": prompt_profile.profile,
    }


def materialize_suite(
    suite_id: str,
    *,
    trials_per_task: int,
    max_steps: int | None = None,
    task_pairs: Iterable[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Serialize a named suite for standalone and training-time consumers."""

    if isinstance(trials_per_task, bool) or not isinstance(trials_per_task, int) or trials_per_task <= 0:
        raise ValueError("GameWorld trials_per_task must be a positive integer")
    pairs = list(task_pairs) if task_pairs is not None else suite_tasks(suite_id)
    trials = [
        materialize_trial(
            game_id,
            task_id,
            trial_index=trial_index,
            max_steps=max_steps,
        )
        for game_id, task_id in pairs
        for trial_index in range(trials_per_task)
    ]
    return {
        "protocol": "gameworld.game-gym.suite.v1",
        "suite_id": str(suite_id),
        "task_count": len(pairs),
        "trials_per_task": trials_per_task,
        "trial_count": len(trials),
        "trials": trials,
    }


__all__ = [
    "GAMEWORLD_170_SUITE",
    "GAMEWORLD_SUITES",
    "GAMEWORLD_BENCHMARK_RELEASE",
    "GAMEWORLD_DEFAULT_MAX_STEPS",
    "materialize_suite",
    "materialize_trial",
    "select_suite_tasks",
    "suite_tasks",
]
