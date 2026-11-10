"""Player-1 dataset with deterministic environment-aware batch composition."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from verl.utils.dataset.rl_dataset import RLHFDataset

from player1.training.data.joint_training import (
    EnvironmentBatchSchedule,
    compile_environment_batch_schedule,
    load_joint_training_config,
)


class PlayerOneDataset(RLHFDataset):
    """Apply a joint-training schedule before verl's native sequential sampler."""

    def __init__(self, *args, **kwargs):
        config = kwargs.get("config")
        if config is None and len(args) >= 3:
            config = args[2]
        if config is None:
            raise ValueError("PlayerOneDataset requires a data config")
        if bool(config.get("shuffle", False)):
            raise ValueError("PlayerOneDataset requires data.shuffle=false; ordering is defined by its schedule")
        config_path = str(config.get("player1_joint_training_config") or "").strip()
        if not config_path:
            raise ValueError("data.player1_joint_training_config is required")
        self.joint_training_config_path = str(Path(config_path).expanduser().resolve())
        self.joint_training_config = load_joint_training_config(self.joint_training_config_path)
        super().__init__(*args, **kwargs)

    def _read_files_and_tokenize(self):
        super()._read_files_and_tokenize()
        self._apply_environment_batch_schedule()

    @staticmethod
    def _row_metadata(row: dict[str, Any], *, physical_index: int) -> dict[str, Any]:
        extra_info = row.get("extra_info")
        if not isinstance(extra_info, dict):
            raise ValueError(f"Player-1 dataset row {physical_index} is missing extra_info")
        for field in (
            "split",
            "preset_spec",
            "environment_id",
            "joint_training_id",
            "history_context_mode",
        ):
            if not str(extra_info.get(field) or "").strip():
                raise ValueError(f"Player-1 dataset row {physical_index} is missing extra_info.{field}")
        return extra_info

    def _infer_split_and_validate_rows(
        self,
        physical_row_indices: list[int] | None = None,
    ) -> tuple[str, dict[str, deque[int]]]:
        if len(self.dataframe) == 0:
            raise ValueError("PlayerOneDataset cannot schedule an empty dataset")

        physical_indices: dict[str, deque[int]] = defaultdict(deque)
        splits: set[str] = set()
        row_indices = physical_row_indices if physical_row_indices is not None else list(range(len(self.dataframe)))
        if not row_indices:
            raise ValueError("PlayerOneDataset cannot schedule an empty Player-1 row selection")
        for physical_index in row_indices:
            row = self.dataframe[physical_index]
            extra_info = self._row_metadata(row, physical_index=physical_index)
            split = str(extra_info["split"])
            environment_id = str(extra_info["environment_id"])
            joint_training_id = str(extra_info["joint_training_id"])
            if joint_training_id != self.joint_training_config.joint_training_id:
                raise ValueError(
                    f"Player-1 dataset row {physical_index} belongs to joint_training_id={joint_training_id!r}; "
                    f"expected {self.joint_training_config.joint_training_id!r}"
                )
            try:
                environment = self.joint_training_config.environment(environment_id)
            except KeyError as exc:
                raise ValueError(str(exc)) from exc
            expected_preset = environment.train_preset_spec
            if extra_info["preset_spec"] != expected_preset:
                raise ValueError(
                    f"Player-1 dataset row {physical_index} has preset_spec={extra_info['preset_spec']!r}; "
                    f"expected {expected_preset!r} for environment_id={environment_id!r} split={split!r}"
                )
            expected_source = f"game-gym/{environment_id}"
            if row.get("data_source") != expected_source:
                raise ValueError(
                    f"Player-1 dataset row {physical_index} has data_source={row.get('data_source')!r}; "
                    f"expected {expected_source!r}"
                )
            splits.add(split)
            physical_indices[environment_id].append(physical_index)

        if len(splits) != 1:
            raise ValueError(f"Player-1 dataset must contain exactly one split, got {sorted(splits)}")
        split = next(iter(splits))
        if split != "train":
            raise ValueError(f"Player-1 training dataset requires split='train', got {split!r}")
        return split, physical_indices

    def _compile_schedule(self) -> EnvironmentBatchSchedule:
        batch_size = int(self.config.get("gen_batch_size") or self.config.get("train_batch_size") or 0)
        return compile_environment_batch_schedule(
            self.joint_training_config,
            total_samples=len(self.dataframe),
            batch_size=batch_size,
        )


    @staticmethod
    def _scheduled_mapping(
        schedule: EnvironmentBatchSchedule,
        physical_indices: dict[str, deque[int]],
    ) -> list[int]:
        actual_counts = {environment_id: len(indices) for environment_id, indices in physical_indices.items()}
        expected_counts = schedule.environment_counts
        if actual_counts != expected_counts:
            raise ValueError(
                "Player-1 dataset environment counts do not match the compiled schedule; "
                f"actual={actual_counts}, expected={expected_counts}. Prompt filtering, max_samples, or a stale "
                "parquet artifact must not silently change joint-training composition."
            )
        return [physical_indices[environment_id].popleft() for environment_id in schedule.environment_ids]

    def _apply_environment_batch_schedule(self) -> None:
        sources = {str(row.get("data_source") or "") for row in self.dataframe}
        if not sources or any(not source.startswith("game-gym/") for source in sources):
            raise ValueError("Player-1 dataset contains an unsupported data source")

        split, physical_indices = self._infer_split_and_validate_rows()
        schedule = self._compile_schedule()
        mapping = self._scheduled_mapping(schedule, physical_indices)
        self.dataframe = self.dataframe.select(mapping)
        print(
            f"PlayerOneDataset joint_training={schedule.joint_training_id} split={split} "
            f"samples={schedule.total_samples} batch_size={schedule.batch_size} "
            f"environment_counts={schedule.environment_counts}"
        )


__all__ = ["PlayerOneDataset"]
