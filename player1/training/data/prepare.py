"""Prepare catalog-driven Player-1 datasets for joint training."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from player1 import build_runtime_config
from player1.training.data.joint_training import (
    EnvironmentBatchSchedule,
    JointTrainingConfig,
    compile_environment_batch_schedule,
    load_joint_training_config,
)
from player1.catalog.visual_perturbation import (
    PERTURBATION_PROFILE_OPTIONS,
    VisualPerturbationConfig,
    compile_visual_perturbation_schedule,
    load_visual_perturbation_config,
)


def build_runtime_metadata(
    preset_spec: str, *, in_context_example_variant: str = "original"
) -> tuple[Any, list[dict[str, str]]]:
    runtime_config = build_runtime_config(preset_spec, in_context_example_variant=in_context_example_variant)
    if not runtime_config.initial_messages:
        raise ValueError(f"No initial prompt messages were generated for {preset_spec!r}.")
    return runtime_config, list(runtime_config.initial_messages)


def build_environment_rows(
    *,
    joint_training: JointTrainingConfig,
    schedule: EnvironmentBatchSchedule,
    seed_start: int,
    visual_perturbation: VisualPerturbationConfig | None = None,
    in_context_example_variant: str = "original",
) -> list[dict[str, Any]]:
    """Build canonical grouped rows; the runtime dataset applies the batch schedule."""

    if schedule.joint_training_id != joint_training.joint_training_id:
        raise ValueError(
            f"schedule belongs to {schedule.joint_training_id!r}, expected {joint_training.joint_training_id!r}"
        )

    counts = Counter(schedule.environment_ids)
    logical_indices_by_environment = {environment.environment_id: [] for environment in joint_training.environments}
    for logical_index, environment_id in enumerate(schedule.environment_ids):
        logical_indices_by_environment[environment_id].append(logical_index)

    perturbation_schedule = None
    if visual_perturbation is not None:
        perturbation_schedule = compile_visual_perturbation_schedule(
            visual_perturbation,
            total_samples=schedule.total_samples,
            batch_size=schedule.batch_size,
        )

    rows: list[dict[str, Any]] = []
    for environment_index, environment in enumerate(joint_training.environments):
        preset_spec = environment.train_preset_spec
        runtime_config, prompt = build_runtime_metadata(
            preset_spec, in_context_example_variant=in_context_example_variant
        )
        for environment_row_index in range(counts[environment.environment_id]):
            index = logical_indices_by_environment[environment.environment_id][environment_row_index]
            extra_info = {
                "split": "train",
                "index": index,
                "preset_spec": preset_spec,
                "in_context_example_variant": in_context_example_variant,
                "environment_id": environment.environment_id,
                "joint_training_id": joint_training.joint_training_id,
                "environment_index": environment_index,
                "train_weight": environment.train_weight,
                "environment_row_index": environment_row_index,
                "game_id": runtime_config.game_id,
                "task_id": runtime_config.task_id,
                "action_format": runtime_config.action_format,
                "action_space_mode": runtime_config.action_space_mode,
                "history_context_mode": runtime_config.history_context_mode,
                "random_seed": seed_start + environment_row_index,
            }
            if perturbation_schedule is not None:
                mode_id = perturbation_schedule[index]
                profiles = visual_perturbation.mode(mode_id).profiles()
                extra_info.update(
                    {
                        "visual_perturbation_id": visual_perturbation.visual_perturbation_id,
                        "visual_perturbation_mode": mode_id,
                        # A default profile stays absent at runtime so Baseline
                        # preserves the original legacy RNG stream exactly.
                        **{
                            option: profiles[domain] if profiles[domain] != "default" else None
                            for domain, option in PERTURBATION_PROFILE_OPTIONS.items()
                        },
                    }
                )
            rows.append(
                {
                    "data_source": f"game-gym/{environment.environment_id}",
                    "prompt": prompt,
                    "ability": "player1_gym",
                    "extra_info": extra_info,
                }
            )
    if len(rows) != schedule.total_samples:
        raise RuntimeError(f"built {len(rows)} rows for a {schedule.total_samples}-sample schedule")
    return rows


def write_split(output_dir: Path, *, name: str, rows: list[dict[str, Any]]) -> Path:
    output_path = output_dir / f"{name}.parquet"
    pq.write_table(pa.Table.from_pylist(rows), output_path)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, help="Directory to write parquet files into.")
    parser.add_argument("--joint-training-config", required=True)
    parser.add_argument("--visual-perturbation-config")
    parser.add_argument("--in-context-example-variant", choices=("original", "basic"), default="basic")
    parser.add_argument("--train-batch-size", type=int, required=True)
    parser.add_argument("--train-count", type=int, default=32)
    parser.add_argument("--train-seed-start", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    joint_training = load_joint_training_config(args.joint_training_config)
    visual_perturbation = (
        load_visual_perturbation_config(args.visual_perturbation_config) if args.visual_perturbation_config else None
    )
    train_schedule = compile_environment_batch_schedule(
        joint_training,
        total_samples=args.train_count,
        batch_size=args.train_batch_size,
    )
    train_rows = build_environment_rows(
        joint_training=joint_training,
        schedule=train_schedule,
        seed_start=args.train_seed_start,
        visual_perturbation=visual_perturbation,
        in_context_example_variant=args.in_context_example_variant,
    )
    train_path = write_split(output_dir, name="train", rows=train_rows)
    environment_summary = ",".join(
        f"{environment.environment_id}:train_weight={environment.train_weight:g}"
        for environment in joint_training.environments
    )
    print(f"prepared joint_training={joint_training.joint_training_id} environments={environment_summary}")
    if visual_perturbation is not None:
        print(
            "prepared visual_perturbation="
            f"{visual_perturbation.visual_perturbation_id}"
        )
    print(f"wrote {train_path}")


if __name__ == "__main__":
    main()
