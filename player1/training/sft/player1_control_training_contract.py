"""Configuration and immutable-path contract for Player-1 Control SFT."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from player1.agents.actions.prompting import PLAYER1_CONTROL_RESPONSE_FORMAT
from player1.training.rollout.config import PlayerOneAgentLoopConfig

from player1.datasets.metadata import PlayerOneControlReleaseFileSnapshot
from player1.datasets.release_reader import validate_dataset_manifest
from player1.datasets.release_contract import RELEASE_MANIFEST_FILE, SPLITS, canonical_image_contract
from player1.training.sft.player1_control_prompt import player1_control_rl_tools
from player1.datasets.storage import (
    S3ReleaseFileSnapshot,
    child,
    is_s3,
    location,
    member_name,
    read_bytes,
)

PLAYER1_CONTROL_DATASET_CLASS_PATH = "pkg://player1.training.sft.player1_control_dataset"
PLAYER1_CONTROL_DATASET_CLASS_NAME = "PlayerOneControlQwen35SFTDataset"
PLAYER1_CONTROL_RESUME_IDENTITY_SCHEMA = "player1.sft.dataset_identity"
_RELEASE_MEMBERS = (RELEASE_MANIFEST_FILE, *(f"{split}.parquet" for split in SPLITS))


@dataclass(frozen=True, slots=True)
class PlayerOneControlTrainingContract:
    """Published release metadata and resume identity for both training splits."""

    release_root: Path | str
    canonical_root: Path | str
    train_file: Path | str
    validation_file: Path | str
    release_manifest: dict[str, Any]
    image_contract: dict[str, str]
    history_projection: dict[str, Any]
    release_files: tuple[PlayerOneControlReleaseFileSnapshot | S3ReleaseFileSnapshot, ...]

    def trajectories(self, split: str) -> list[dict[str, Any]]:
        return sorted(
            (entry for entry in self.release_manifest["trajectories"] if entry["split"] == split),
            key=lambda entry: entry["row_group"],
        )

    def snapshot_for(self, path: str | os.PathLike[str]) -> PlayerOneControlReleaseFileSnapshot | S3ReleaseFileSnapshot:
        resolved = location(path)
        for snapshot in self.release_files:
            if snapshot.path == resolved:
                return snapshot
        raise ValueError(f"path is not a member of the frozen Player-1 Control release: {resolved}")

    def assert_current(self) -> None:
        for snapshot in self.release_files:
            snapshot.assert_current()

    def assert_metadata_current(self) -> None:
        self.assert_current()

    def release_content_identity(self) -> dict[str, Any]:
        def identity(snapshot: PlayerOneControlReleaseFileSnapshot | S3ReleaseFileSnapshot) -> dict[str, Any]:
            if isinstance(snapshot, S3ReleaseFileSnapshot):
                return snapshot.content_identity()
            return {
                "name": snapshot.path.name,
                "size_bytes": snapshot.size,
                "modified_ns": snapshot.modified_ns,
            }

        return {
            "release_members": [
                identity(item) for item in sorted(self.release_files, key=lambda item: member_name(item.path))
            ],
        }

    def resume_identity(self) -> dict[str, Any]:
        return {
            "schema_version": PLAYER1_CONTROL_RESUME_IDENTITY_SCHEMA,
            "release_manifest": deepcopy(self.release_manifest),
            "release_content": self.release_content_identity(),
            "model_input": {
                "history_projection": deepcopy(self.history_projection),
                "prefix_renderer": "player1.agents.prompting.render_initial_messages",
                "response_format": PLAYER1_CONTROL_RESPONSE_FORMAT,
                # Keep order: JSON object order also changes model-facing tokens.
                "tools_json": json.dumps(player1_control_rl_tools(), ensure_ascii=False, separators=(",", ":")),
            },
        }


def _config_value(config: Any, key: str) -> Any:
    getter = getattr(config, "get", None)
    return getter(key) if callable(getter) else getattr(config, key, None)


def player1_control_training_history(config: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve training/eval capacities independently of immutable release metadata."""
    defaults = PlayerOneAgentLoopConfig()
    projection = {}
    for layer, key, mode in (
        ("recent", "history_context_turns", "v_a"),
        ("old", "history_context_old_turns", "a"),
    ):
        turns = config.get(key, getattr(defaults, key))
        if isinstance(turns, bool) or not isinstance(turns, int) or turns < 0:
            raise ValueError(f"SFT {key} must be a non-negative integer")
        projection[layer] = {"turns": turns, "mode": mode}
    return projection


def _exact_file(value: Any, *, expected: Path | str, field: str) -> Path | str:
    if isinstance(value, (str, os.PathLike)):
        paths = [value]
    else:
        try:
            paths = list(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Player-1 Control {field} must contain exactly {expected}") from error
    if len(paths) != 1 or not isinstance(paths[0], (str, os.PathLike)):
        raise ValueError(f"Player-1 Control {field} must contain exactly {expected}")
    selected = paths[0]
    if (not is_s3(selected) and Path(selected).expanduser().is_symlink()) or location(selected) != expected:
        raise ValueError(f"Player-1 Control {field} must contain exactly {expected}")
    return expected


def _metadata_identity(path: Path) -> tuple[int, int, int, int, int]:
    return PlayerOneControlReleaseFileSnapshot._identity(path.lstat())


@lru_cache(maxsize=16)
def _capture_snapshot(
    path: Path,
    _identity: tuple[int, int, int, int, int],
) -> PlayerOneControlReleaseFileSnapshot:
    return PlayerOneControlReleaseFileSnapshot.capture(path)


def _snapshot(path: Path | str) -> PlayerOneControlReleaseFileSnapshot | S3ReleaseFileSnapshot:
    if is_s3(path):
        return S3ReleaseFileSnapshot.capture(path)
    return _capture_snapshot(path, _metadata_identity(path))


def _root(value: Any, *, field: str) -> Path | str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Player-1 Control requires data.{field}")
    if is_s3(value):
        return location(value)
    selected = Path(value).expanduser()
    if selected.is_symlink():
        raise ValueError(f"Player-1 Control {field} must not be a symlink")
    root = selected.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Player-1 Control {field} must be a directory: {root}")
    return root


def load_player1_control_training_contract(data_config: Any) -> PlayerOneControlTrainingContract:
    """Load published metadata without scanning Parquet rows or listing images."""

    root = _root(_config_value(data_config, "player1_control_dataset_root"), field="player1_control_dataset_root")
    release_root, canonical_root = child(root, "data"), child(root, "images")
    custom_cls = _config_value(data_config, "custom_cls")
    if not isinstance(custom_cls, Mapping) or dict(custom_cls) != {
        "path": PLAYER1_CONTROL_DATASET_CLASS_PATH,
        "name": PLAYER1_CONTROL_DATASET_CLASS_NAME,
    }:
        raise ValueError(
            "Player-1 Control data.custom_cls must select "
            f"{PLAYER1_CONTROL_DATASET_CLASS_PATH}:{PLAYER1_CONTROL_DATASET_CLASS_NAME}"
        )
    train_file = _exact_file(
        _config_value(data_config, "train_files"),
        expected=child(release_root, "train.parquet"),
        field="train_files",
    )
    validation_file = _exact_file(
        _config_value(data_config, "val_files") or [child(release_root, "validation.parquet")],
        expected=child(release_root, "validation.parquet"),
        field="val_files",
    )
    snapshots = tuple(_snapshot(child(release_root, name)) for name in _RELEASE_MEMBERS)
    manifest = validate_dataset_manifest(json.loads(read_bytes(child(release_root, RELEASE_MANIFEST_FILE))))
    for split in SPLITS:
        groups = [entry["row_group"] for entry in manifest["trajectories"] if entry["split"] == split]
        if sorted(groups) != list(range(len(groups))):
            raise ValueError("SFT trajectory row groups must be contiguous within each split")
    contract = PlayerOneControlTrainingContract(
        release_root=release_root,
        canonical_root=canonical_root,
        train_file=train_file,
        validation_file=validation_file,
        release_manifest=deepcopy(manifest),
        image_contract=canonical_image_contract(),
        history_projection=player1_control_training_history(data_config),
        release_files=snapshots,
    )
    contract.assert_current()
    return contract


__all__ = [
    "PLAYER1_CONTROL_DATASET_CLASS_NAME",
    "PLAYER1_CONTROL_DATASET_CLASS_PATH",
    "PLAYER1_CONTROL_RESUME_IDENTITY_SCHEMA",
    "PlayerOneControlReleaseFileSnapshot",
    "PlayerOneControlTrainingContract",
    "load_player1_control_training_contract",
]
