"""Read one current target and its reconstructed history from a portable bundle."""

import argparse
from pathlib import Path

from player1.datasets.dataset import Dataset

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("root", type=Path)
parser.add_argument("--turn", type=int, default=0)
args = parser.parse_args()
data = Dataset(
    args.root,
    split="train",
    recent_turns=2,
    old_turns=2,
)
try:
    example = data[args.turn]
    assert sum(example["message_loss_mask"]) == 1
    print(example["messages"][-1]["content"])
    print(f"Supervised messages: {sum(example['message_loss_mask'])}")
finally:
    data.close()
