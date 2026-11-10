"""Default overlapping action-category mixtures for current-turn SFT targets.

Draw a category, then a row uniformly within it, with replacement. Equal
category weights are NOT equal marginal action frequencies: one row may
belong to several categories. Dataset history projection remains untouched.
"""

from __future__ import annotations

import math
import random
from array import array
from collections.abc import Iterator, Mapping
from typing import Any

from player1.agents.actions.parser import PlayerOneActionParser
from player1.agents.actions.serialization import ACTION_FORMAT_QWEN3_CODER_XML

ACTION_CATEGORIES = (
    "keyboard", "mouse_move", "mouse_click", "mouse_hold", "mouse_button",
    "keyboard_mouse", "move_click", "keyboard_click", "keyboard_move_click", "other",
)
BALANCED_MODE = "action_balanced"


def _balanced_options(weights: Mapping[str, Any], uniform_fraction: float) -> tuple[dict[str, float], float]:
    if not isinstance(weights, Mapping):
        raise ValueError("Action sampler weights must be a mapping of category names to numbers")
    unknown = set(weights) - set(ACTION_CATEGORIES)
    if unknown:
        raise ValueError(f"Unknown action sampler categories: {sorted(unknown)}")
    resolved = {}
    for name in ACTION_CATEGORIES:
        value = weights.get(name, 0.1 if name == "other" else 1.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Action sampler weight {name} must be finite and non-negative")
        resolved[name] = float(value)
    if (
        isinstance(uniform_fraction, bool)
        or not isinstance(uniform_fraction, (int, float))
        or not math.isfinite(uniform_fraction)
        or not 0 <= uniform_fraction <= 1
    ):
        raise ValueError("Action sampler uniform_fraction must be in [0, 1]")
    if uniform_fraction < 1 and not any(resolved.values()):
        raise ValueError("Action sampler requires a positive category weight unless uniform_fraction=1")
    return resolved, float(uniform_fraction)


def sampling_config(raw: Mapping[str, Any] | None, *, seed: int) -> dict[str, Any]:
    """Normalize the sole SFT sampler and its checkpoint-bound configuration."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping) or set(raw) - {"mode", "weights", "uniform_fraction"}:
        raise ValueError("sampling must contain only mode, weights and uniform_fraction")
    if raw.get("mode", BALANCED_MODE) != BALANCED_MODE:
        raise ValueError(f"SFT only supports {BALANCED_MODE}")
    weights, fraction = _balanced_options(raw.get("weights", {}), raw.get("uniform_fraction", 0.0))
    return {"mode": BALANCED_MODE, "seed": seed, "drop_last": True,
            "weights": weights, "uniform_fraction": fraction}


def action_categories(action: str, parser: PlayerOneActionParser) -> tuple[str, ...]:
    """Classify the canonical CURRENT action, never history or an ICL example."""
    parsed = parser.parse_action_frame_with_span(action)
    if parsed is None:
        raise ValueError("Cannot classify canonical_action for the action-balanced sampler")
    calls = {call["tool_name"]: call["arguments"] for call in parsed[0]["tool_calls"]}
    key, mouse = calls.get("key_control", {}), calls.get("mouse_control", {})
    keyboard = bool(key.get("key_hold") or key.get("key_tap"))
    move = bool(mouse.get("mouse_move"))
    click, hold = bool(mouse.get("mouse_click")), bool(mouse.get("mouse_hold"))
    mouse_any = move or click or hold or bool(mouse.get("mouse_scroll"))
    present = (
        keyboard, move, click, hold, click or hold, keyboard and mouse_any,
        move and click, keyboard and click, keyboard and move and click,
        not (keyboard or move or click or hold),
    )
    return tuple(name for name, enabled in zip(ACTION_CATEGORIES, present, strict=True) if enabled)


class ActionBalancedBatchSampler:
    """One seeded global schedule, dispatched by the trainer across all DP ranks.

    The epoch still has floor(len(dataset) / global_batch_size) updates. Rows
    can repeat within/across batches and ranks, intentionally. No model/media
    processing occurs while building the compact row-index pools.
    """

    def __init__(
        self, dataset: Any, *, global_batch_size: int, data_parallel_size: int,
        seed: int = 42, weights: Mapping[str, float] | None = None, uniform_fraction: float = 0.0,
    ) -> None:
        for name, value in (("global_batch_size", global_batch_size), ("data_parallel_size", data_parallel_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Player-1 Control {name} must be a positive integer")
        if global_batch_size % data_parallel_size:
            raise ValueError("Player-1 Control global batch size must be divisible by actor DP size")
        if len(dataset) < global_batch_size:
            raise ValueError("Player-1 Control training split must contain one complete global batch")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("Player-1 Control sampler seed must be an integer")
        self.dataset = dataset
        self.global_batch_size = global_batch_size
        self.seed = seed
        self.epoch = 0
        self.weights, self.uniform_fraction = _balanced_options(
            weights if weights is not None else {}, uniform_fraction,
        )
        pools = {name: array("q") for name in ACTION_CATEGORIES}
        parser = PlayerOneActionParser(ACTION_FORMAT_QWEN3_CODER_XML, action_space_mode="player1_control")
        count = 0
        for index, action in enumerate(dataset.iter_canonical_actions()):
            for category in action_categories(action, parser):
                pools[category].append(index)
            count += 1
        if count != len(dataset):
            raise ValueError("Action sampler index count differs from dataset length")
        self.category_counts = {name: len(pool) for name, pool in pools.items()}
        active = [name for name in ACTION_CATEGORIES if self.weights[name] > 0 and self.uniform_fraction < 1]
        empty = [name for name in active if not pools[name]]
        if empty:
            raise ValueError(f"Action sampler categories have no rows: {empty}; explicitly set their weights to 0")
        self._pools = [pools[name] for name in active]
        # Scale before summing so finite, very large user weights cannot overflow.
        scale = max((self.weights[name] for name in active), default=1.0)
        scaled = [self.weights[name] / scale for name in active]
        total = sum(scaled)
        self._probabilities = [(1 - self.uniform_fraction) * weight / total for weight in scaled]
        if self.uniform_fraction:
            self._pools.append(range(len(dataset)))
            self._probabilities.append(self.uniform_fraction)

    def __len__(self) -> int:
        return len(self.dataset) // self.global_batch_size

    def set_epoch(self, epoch: int) -> None:
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise ValueError("Player-1 Control sampler epoch must be a non-negative integer")
        self.epoch = epoch

    def __iter__(self) -> Iterator[list[int]]:
        rng = random.Random(self.seed + self.epoch)
        for _ in range(len(self)):
            pools = rng.choices(self._pools, weights=self._probabilities, k=self.global_batch_size)
            yield [rng.choice(pool) for pool in pools]


def build_train_sampler(
    dataset: Any, *, global_batch_size: int, data_parallel_size: int, sampling: Mapping[str, Any],
) -> ActionBalancedBatchSampler:
    if sampling["mode"] != BALANCED_MODE:
        raise ValueError(f"SFT only supports {BALANCED_MODE}")
    return ActionBalancedBatchSampler(
        dataset, global_batch_size=global_batch_size, data_parallel_size=data_parallel_size,
        seed=sampling["seed"], weights=sampling["weights"], uniform_fraction=sampling["uniform_fraction"],
    )


class RankBatchSampler:
    """Select one DP shard from the same deterministic global sampling schedule."""

    def __init__(self, sampler, *, rank: int, size: int):
        if size <= 0 or not 0 <= rank < size:
            raise ValueError("Invalid data-parallel rank/size")
        self.sampler, self.rank, self.size = sampler, rank, size

    def __len__(self):
        return len(self.sampler)

    def set_epoch(self, epoch):
        self.sampler.set_epoch(epoch)

    def __iter__(self):
        for batch in self.sampler:
            if len(batch) % self.size:
                raise ValueError("Global batch size must be divisible by the DP size")
            count = len(batch) // self.size
            yield batch[self.rank * count:(self.rank + 1) * count]
