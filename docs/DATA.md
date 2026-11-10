# Player-1-Data

[Download Player-1-Data](https://huggingface.co/datasets/yyyang/Player-1-Data): 6,044 trajectories from 172 games, published as JSON and JPEGs. Follow the dataset card to prepare the training format:

```text
dataset/
  data/
    manifest.json
    train.parquet
    validation.parquet
  images/trajectories/<trajectory-id>/<frame>.jpg
```

Set `PLAYER1_DATASET_ROOT` to this directory for [SFT](TRAINING.md). The published conversion has an empty validation split.

---

## Read and Validate

Install dependencies:

```bash
conda run -n verl pip install -r requirements/data.txt
```

Use the `Dataset` class to read trajectories with reconstructed visual-action history:

```python
from pathlib import Path
from player1.datasets.dataset import Dataset

data_root = Path("/path/to/Player-1-Data")

dataset = Dataset(
    data_root,
    split="train",
    recent_turns=2,  # Turns with full screenshots
    old_turns=2,     # Older turns retaining actions only
)
try:
    example = dataset[0]
    print("Instruction:", example["messages"][0]["content"])
    print("Target action:", example["messages"][-1]["content"])
    print(f"Supervised message count: {sum(example['message_loss_mask'])}")
finally:
    dataset.close()
```

Each Parquet row group is one trajectory. Rows store the current screenshot, instructions, reasoning, and canonical action; `data/manifest.json` records provenance and splits. Keep `data/` and `images/` together.

[read_dataset.py](../examples/data/read_dataset.py) reconstructs recent visual and older action-only history. See [Data production](DATA_PRODUCTION.md) to create datasets or open their Viewer:

```bash
python -m player1_data view /path/to/Player-1-Data --port 8765
```
