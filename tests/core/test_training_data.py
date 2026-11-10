"""Prepare training rows through the published catalog and Parquet writer."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from player1.training.data.joint_training import (
    compile_environment_batch_schedule,
    load_joint_training_config,
)
from player1.training.data.prepare import build_environment_rows, write_split


def _write_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "joint_training_id": "aim_movement_test",
                "environments": [
                    {
                        "environment_id": "base_3d_aim",
                        "train_preset_spec": "base_3d_aim+base_3d_aim_train+qwen3.5-baserl",
                        "train_weight": 1,
                    },
                    {
                        "environment_id": "base_3d_movement",
                        "train_preset_spec": "base_3d_movement+base_3d_movement_train+qwen3.5-baserl",
                        "train_weight": 1,
                    },
                ],
            }
        )
    )
    return path


def _write_rows(
    tmp_path: Path, config_path: Path, *, total_samples: int,
    in_context_example_variant: str = "original",
) -> Path:
    config = load_joint_training_config(config_path)
    schedule = compile_environment_batch_schedule(
        config,
        total_samples=total_samples,
        batch_size=4,
    )
    rows = build_environment_rows(
        joint_training=config,
        schedule=schedule,
        seed_start=100,
        in_context_example_variant=in_context_example_variant,
    )
    return write_split(tmp_path, name="train", rows=rows)


def test_prepared_gamegym_rows_use_original_ice(tmp_path: Path) -> None:
    from player1 import build_runtime_config

    path = _write_rows(tmp_path, _write_config(tmp_path / "joint.json"), total_samples=4)
    for row in pq.read_table(path).to_pylist():
        preset = row["extra_info"]["preset_spec"]
        assert row["prompt"] == build_runtime_config(preset, in_context_example_variant="original").initial_messages
        assert row["prompt"] != build_runtime_config(preset, in_context_example_variant="basic").initial_messages


def test_prepared_gamegym_rows_select_basic_ice(tmp_path: Path) -> None:
    from player1 import build_runtime_config

    path = _write_rows(
        tmp_path, _write_config(tmp_path / "joint.json"), total_samples=4,
        in_context_example_variant="basic",
    )
    for row in pq.read_table(path).to_pylist():
        preset = row["extra_info"]["preset_spec"]
        assert row["extra_info"]["in_context_example_variant"] == "basic"
        assert row["prompt"] == build_runtime_config(preset, in_context_example_variant="basic").initial_messages
        assert row["prompt"] != build_runtime_config(preset, in_context_example_variant="original").initial_messages
