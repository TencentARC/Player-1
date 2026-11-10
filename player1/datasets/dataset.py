"""Framework-neutral, row-group-bounded access to compact recorded trajectories."""

from __future__ import annotations

import io
from bisect import bisect_right
from copy import deepcopy
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image

from player1.agents.history_context import (
    HISTORY_CONTEXT_MESSAGE_METADATA_KEY,
    build_history_context_metadata,
    select_history_context_messages,
)
from player1.datasets.metadata import PlayerOneControlReleaseFileSnapshot
from player1.datasets.release_contract import (
    SPLITS,
    canonical_image_contract,
    player1_control_history_projection_contract,
)
from player1.datasets.release_reader import CanonicalImageStore, validate_dataset_structure


def project_turn(records: list[dict], index: int, *, recent_turns: int, old_turns: int) -> dict:
    """Reconstruct visual/action history while supervising only the current assistant.

    History capacities count prior turns. Segment boundaries truncate both layers;
    old history carries actions only, recent history carries image + action.
    The boolean loss mask is message-level; tokenization belongs to the consumer.
    """
    if any(type(n) is not int or n < 0 for n in (recent_turns, old_turns)):
        raise ValueError("history capacities must be nonnegative integers")
    source = records[index]
    messages = source["messages"]
    count = min(index, source["segment_turn_index"], recent_turns + old_turns)
    recent = min(count, recent_turns)
    visual_indices = [*range(index - recent, index), index]
    ledger = deepcopy(messages[:2])
    for turn in range(index - count, index + 1):
        record = records[turn]
        content = record["messages"][2]["content"]
        if len(record["images"]) != 1 or not content.startswith("<image>\n"):
            raise ValueError("release observation must contain exactly one current image")
        ledger.append(
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": record["images"][0]["image"]},
                    {"type": "text", "text": content[len("<image>\n") :]},
                ],
            }
        )
        if turn < index:
            action = record["canonical_action"]
            ledger.append(
                {
                    "role": "assistant",
                    "content": action,
                    HISTORY_CONTEXT_MESSAGE_METADATA_KEY: build_history_context_metadata(
                        "v_a", action, replay_source="admitted"
                    ),
                }
            )
    selected, _ = select_history_context_messages(
        messages=ledger,
        initial_prompt_message_count=2,
        history_context_turns=recent_turns,
        history_context_mode="v_a",
        history_context_old_turns=old_turns,
        history_context_old_mode="a",
    )
    projected = [{"role": message["role"], "content": message["content"]} for message in selected]
    projected.append(deepcopy(messages[-1]))
    return {
        **deepcopy(source),
        "messages": projected,
        "images": [deepcopy(records[i]["images"][0]) for i in visual_indices],
        "loss_target_message_index": len(projected) - 1,
        "message_loss_mask": [False] * (len(projected) - 1) + [True],
        "history_context": {
            "prior_sample_ids": [r["sample_id"] for r in records[index - count : index]],
            "history_turns": recent_turns + old_turns,
            "segment_turn_index": source["segment_turn_index"],
            "reset_at_segment_start": True,
            "assistant_loss_scope": "current_only",
        },
    }


class Dataset:
    """Read current-turn rows or projected examples without Torch or a model."""

    def __init__(
        self,
        root: str | Path,
        *,
        split: str = "train",
        recent_turns: int | None = None,
        old_turns: int | None = None,
    ):
        if split not in SPLITS:
            raise ValueError("unknown split")
        root = Path(root).expanduser().resolve(strict=True)
        snapshot = PlayerOneControlReleaseFileSnapshot.capture(root / "data" / f"{split}.parquet")
        manifest = validate_dataset_structure(root / "data", canonical_root=root / "images")
        snapshot.assert_current()
        images = CanonicalImageStore(canonical_image_contract(), canonical_root=root / "images")
        self._initialize(manifest, snapshot, images, split, recent_turns, old_turns)

    @classmethod
    def open_splits(cls, root: str | Path):
        root = Path(root).expanduser().resolve(strict=True)
        snapshots = {
            split: PlayerOneControlReleaseFileSnapshot.capture(root / "data" / f"{split}.parquet") for split in SPLITS
        }
        manifest = validate_dataset_structure(root / "data", canonical_root=root / "images")
        for snapshot in snapshots.values():
            snapshot.assert_current()
        images = CanonicalImageStore(canonical_image_contract(), canonical_root=root / "images")
        result = {}
        for split, snapshot in snapshots.items():
            view = cls.__new__(cls)
            view._initialize(manifest, snapshot, images, split, None, None)
            result[split] = view
        return result

    def _initialize(self, manifest, snapshot, images, split, recent_turns, old_turns):
        self.manifest, self.snapshot, self.images = manifest, snapshot, images
        history = player1_control_history_projection_contract()
        self.recent = history["recent"]["turns"] if recent_turns is None else recent_turns
        self.old = history["old"]["turns"] if old_turns is None else old_turns
        if any(type(n) is not int or n < 0 for n in (self.recent, self.old)):
            raise ValueError("history capacities must be nonnegative integers")
        self.offsets = [0]
        self.groups = sorted(
            (t for t in self.manifest["trajectories"] if t["split"] == split), key=lambda t: t["row_group"]
        )
        for group in self.groups:
            self.offsets.append(self.offsets[-1] + group["rows"])
        self._cached_group, self._records = -1, []

    def __len__(self):
        return self.offsets[-1]

    def _locate(self, index):
        self.snapshot.assert_current()
        if not 0 <= index < len(self):
            raise IndexError(index)
        group = bisect_right(self.offsets, index) - 1
        if group != self._cached_group:
            with self.snapshot.open_metadata_verified() as stream, pq.ParquetFile(stream) as parquet:
                self._records = parquet.read_row_group(group).to_pylist()
            self.snapshot.assert_current()
            self._cached_group = group
        return index - self.offsets[group]

    def stored_row(self, index):
        local = self._locate(index)
        return deepcopy(self._records[local])

    def trajectories(self):
        """Yield stored trajectories from this split, using the same bounded row-group reader."""
        for offset in self.offsets[:-1]:
            self._locate(offset)
            yield deepcopy(self._records)

    def image(self, reference):
        with Image.open(io.BytesIO(self.images.read(reference))) as image:
            return image.convert("RGB")

    def row(self, index):
        local = self._locate(index)
        return project_turn(self._records, local, recent_turns=self.recent, old_turns=self.old)

    __getitem__ = row

    def close(self):
        self._cached_group, self._records = -1, []
