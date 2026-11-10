"""Prepare seeded Gym rows using explicit environment and randomization settings."""

from pathlib import Path

from player1.catalog.visual_perturbation import load_visual_perturbation_config
from player1.training.data.joint_training import compile_environment_batch_schedule, load_joint_training_config
from player1.training.data.prepare import build_environment_rows, write_split

OUTPUT = Path("outputs/training/data")
ENVIRONMENTS = Path(__file__).with_name("environments.json")
RANDOMIZATION = Path(__file__).with_name("randomization.json")
BATCH_SIZE = 16
TRAIN_ROWS = 128


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    environments = load_joint_training_config(ENVIRONMENTS)
    randomization = load_visual_perturbation_config(RANDOMIZATION)
    schedule = compile_environment_batch_schedule(
        environments, batch_size=BATCH_SIZE, total_samples=TRAIN_ROWS,
    )
    rows = build_environment_rows(
        joint_training=environments, schedule=schedule, seed_start=0,
        visual_perturbation=randomization, in_context_example_variant="basic",
    )
    print(write_split(OUTPUT, name="train", rows=rows))


if __name__ == "__main__":
    main()
