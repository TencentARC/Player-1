"""Per-draw history projection, independent of action-balanced row selection."""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import NamedTuple

HISTORY_CHOICES = tuple((recent, old) for recent in range(3) for old in range(3))


class HistorySampleIndex(NamedTuple):
    row_index: int
    recent_turns: int
    old_turns: int


class UniformHistoryBatchSampler:
    """Decorate draws without changing their order or consuming the action RNG.

    Each draw independently selects one of nine capacities with probability 1/9. Replaying
    from the same epoch/seed reproduces indices for StatefulDataLoader resume;
    workers never draw random context or mutate a Dataset-wide history setting.
    """

    def __init__(self, sampler) -> None:
        self.sampler = sampler

    def __len__(self) -> int:
        return len(self.sampler)

    def set_epoch(self, epoch: int) -> None:
        self.sampler.set_epoch(epoch)

    def __iter__(self) -> Iterator[list[HistorySampleIndex]]:
        rng = random.Random(f"sft-history:{self.sampler.seed}:{self.sampler.epoch}")
        for batch in self.sampler:
            projected = []
            for index in batch:
                recent, old = rng.choice(HISTORY_CHOICES)
                projected.append(HistorySampleIndex(index, recent, old))
            yield projected
