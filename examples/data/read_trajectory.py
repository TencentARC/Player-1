"""Read one trajectory and resolve its first screenshot from a frozen snapshot."""

from pathlib import Path

from player1.datasets.dataset import Dataset

DATASET_ROOT = Path("/path/to/dataset")


def main():
    dataset = Dataset(DATASET_ROOT, split="train")
    try:
        trajectory = next(dataset.trajectories())
        print({"turns": len(trajectory), "first_sample_id": trajectory[0]["sample_id"]})
        print({"image_size": dataset.image(trajectory[0]["images"][0]).size})
    finally:
        dataset.close()


if __name__ == "__main__":
    main()
