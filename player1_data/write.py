"""One current-turn Parquet writer using the shared published data contract."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from player1.agents.actions.prompting import InContextExample
from player1.agents.prompting import DEFAULT_ACTION_PROMPT_TEXT
from player1.datasets.collection_contract import COLLECTION_SCHEMA, identity_key, session_split
from player1.datasets.player1_control import ACTION_SPACE_MODE, render_initial_messages
from player1.datasets.release_contract import (
    DATA_PRODUCTION_ANNOTATION_PROCEDURE,
    PARQUET_SCHEMA_VERSION,
    SPLITS,
    player1_control_parquet_schema,
    validate_player1_control_path_record,
)
from player1.datasets.release_reader import validate_dataset_structure
from player1_data.files import canonical_json_bytes, publish_staged_immutable_directory


def _json(path, value):
    path.write_bytes(canonical_json_bytes(value, field=path.name))


def write_dataset(annotated, output: Path, *, split_seed="player1-data", validation_basis_points=0):
    """Publish a new, self-contained snapshot. One row group is one complete trajectory."""
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.parent == output:
        raise ValueError("Dataset output must be a new non-root directory")
    output = output.resolve()
    if (
        not isinstance(split_seed, str)
        or not split_seed
        or type(validation_basis_points) is not int
        or not 0 <= validation_basis_points <= 10000
    ):
        raise ValueError("An explicit seed and validation basis points in [0,10000] are required")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.writing-", dir=output.parent)).resolve()
    try:
        release, canonical = staging / "data", staging / "images"
        release.mkdir()
        canonical.mkdir()
        row_groups = {split: 0 for split in SPLITS}
        trajectories, seen, sample_ids = [], set(), set()
        with ExitStack() as stack:
            writers = {
                split: stack.enter_context(
                    pq.ParquetWriter(release / f"{split}.parquet", player1_control_parquet_schema(), compression="zstd")
                )
                for split in SPLITS
            }
            for item in annotated:
                root, prepared = Path(item["root"]).resolve(strict=True), item["trajectory"]
                identity, turns = prepared["identity"], prepared["turns"]
                key = identity_key(identity)
                if key in seen:
                    raise ValueError("Repeated trajectory identity")
                seen.add(key)
                if len(item["reasoning"]) != len(turns) or len(turns) != 50 and prepared["kind"] != "gui":
                    raise ValueError("Incomplete annotation coverage")
                if prepared["kind"] == "gui" and not 25 <= len(turns) <= 50:
                    raise ValueError("GUI trajectories require 25–50 complete turns")
                if output == root or output.is_relative_to(root) or root.is_relative_to(output):
                    raise ValueError("Dataset output must be disjoint from annotation inputs")
                publication = "trajectory-" + prepared["binding"][:24]
                profile = item["profile"]
                example = profile["example"]
                controls = "\n".join(f"{k}: {v}" for k, v in profile["controls"].items())
                initial = render_initial_messages(
                    game_rules=f"Game: {prepared['game']['name']}\nVersion: {prepared['game']['version']}\n"
                    + profile["rules"],
                    task_prompt=item["task"],
                    role_control_block=controls,
                    action_space_mode=ACTION_SPACE_MODE,
                    in_context_example=InContextExample(
                        "observe and act", "<think>\n" + example["reasoning"] + "\n</think>\n\n" + example["action"]
                    ),
                )
                records = []
                for index, (turn, reasoning) in enumerate(zip(turns, item["reasoning"], strict=True)):
                    if turn["index"] != index:
                        raise ValueError("Trajectory is not contiguous")
                    source = (root / turn["image"]).resolve(strict=True)
                    if not source.is_relative_to(root):
                        raise ValueError("Prepared observation changed or escaped its directory")
                    before = source.stat()
                    image = source.read_bytes()
                    after = source.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError(f"Input changed while reading: {source}")
                    if hashlib.sha256(image).hexdigest() != turn["image_sha256"]:
                        raise ValueError("Prepared observation changed or escaped its directory")
                    relative = f"trajectories/{publication}/frames/{index:04d}.jpg"
                    target = canonical / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(image)
                    sample_id = publication + f"-turn-{index:04d}"
                    if sample_id in sample_ids:
                        raise ValueError("Repeated sample identity")
                    sample_ids.add(sample_id)
                    record = {
                        "schema_version": PARQUET_SCHEMA_VERSION,
                        "sample_id": sample_id,
                        "source_key": identity["adapter_id"],
                        "source_weight": 1.0,
                        "messages": [
                            *initial,
                            {"role": "user", "content": "<image>\n" + DEFAULT_ACTION_PROMPT_TEXT},
                            {
                                "role": "assistant",
                                "content": "<think>\n" + reasoning + "\n</think>\n\n" + turn["canonical_action"],
                            },
                        ],
                        "images": [{"image": relative, "size_bytes": len(image)}],
                        "segment_turn_index": index,
                        "canonical_action": turn["canonical_action"],
                    }
                    validate_player1_control_path_record(record)
                    records.append(record)
                split = session_split(identity, split_seed, validation_basis_points)
                writers[split].write_table(
                    pa.Table.from_pylist(records, schema=player1_control_parquet_schema()), row_group_size=len(records)
                )
                trajectories.append(
                    {
                        "id": publication,
                        "source": identity,
                        "mode": prepared["kind"],
                        "split": split,
                        "row_group": row_groups[split],
                        "rows": len(records),
                        "annotation": {
                            "model": item["provider"]["model"],
                            "procedure": DATA_PRODUCTION_ANNOTATION_PROCEDURE,
                            "input_sha256": prepared["binding"],
                        },
                    }
                )
                row_groups[split] += 1
        if not trajectories:
            raise ValueError("Cannot publish an empty dataset")
        manifest = {
            "schema_version": COLLECTION_SCHEMA,
            "split_seed": split_seed,
            "validation_basis_points": validation_basis_points,
            "trajectories": trajectories,
        }
        _json(release / "manifest.json", manifest)
        validate_dataset_structure(release, canonical_root=canonical)
        publish_staged_immutable_directory(output.resolve(), staging, field="Player-1 dataset")
        return manifest
    finally:
        if staging.exists():
            if staging.parent != output.parent.resolve():
                raise ValueError("Unexpected dataset staging cleanup path")
            shutil.rmtree(staging)
