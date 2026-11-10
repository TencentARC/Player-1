"""Export a completed native SFT checkpoint for subsequent RL training."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from filelock import FileLock

DEFAULT_OUTPUT = "outputs/training/sft"


def latest_checkpoint(output: Path) -> Path:
    step = int((output / "latest_checkpointed_iteration.txt").read_text().strip())
    checkpoint = output / f"global_step_{step}"
    if step < 1 or not (checkpoint / "player1.json").is_file():
        raise ValueError(f"No completed Player-1 SFT checkpoint in {output}")
    return checkpoint


def export_identity(checkpoint: Path) -> dict:
    shards = sorted(checkpoint.glob("model_world_size_*_rank_*.pt"))
    if not shards:
        raise ValueError(f"SFT checkpoint has no native model shards: {checkpoint}")
    model_shards = {}
    for path in shards:
        with path.open("rb") as stream:
            model_shards[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"checkpoint": checkpoint.name,
            "player1_sha256": hashlib.sha256((checkpoint / "player1.json").read_bytes()).hexdigest(),
            "model_shards": model_shards}


def _require_export(model: Path, identity: dict) -> Path:
    if json.loads((model / "player1-export.json").read_text()) != identity:
        raise ValueError(f"SFT export identity mismatch: {model}")
    if not (model / "config.json").is_file() or not list(model.glob("*.safetensors")):
        raise ValueError(f"SFT export is incomplete: {model}")
    return model


def exported_model(output: Path) -> Path:
    checkpoint = latest_checkpoint(output)
    return _require_export(checkpoint / "exported-model", export_identity(checkpoint))


def export_checkpoint(output: Path) -> Path:
    checkpoint = latest_checkpoint(output)
    target = checkpoint / "exported-model"
    with FileLock(checkpoint / ".player1-export.lock"):
        if latest_checkpoint(output) != checkpoint:
            raise ValueError(f"SFT checkpoint changed during export: {checkpoint}")
        identity = export_identity(checkpoint)
        try:
            return _require_export(target, identity)
        except (FileNotFoundError, ValueError):
            pass
        with tempfile.TemporaryDirectory(prefix="export-", dir=checkpoint) as temporary:
            model = Path(temporary) / "model"
            subprocess.run([sys.executable, "-m", "verl.model_merger", "merge", "--backend", "fsdp",
                            "--local_dir", str(checkpoint), "--target_dir", str(model)], check=True)
            if latest_checkpoint(output) != checkpoint or export_identity(checkpoint) != identity:
                raise ValueError(f"SFT checkpoint changed during export: {checkpoint}")
            (model / "player1-export.json").write_text(json.dumps(identity, indent=2) + "\n")
            _require_export(model, identity)
            previous = Path(temporary) / "previous-model"
            if target.exists():
                target.rename(previous)
            try:
                model.rename(target)
            except BaseException:
                if previous.exists() and not target.exists():
                    previous.rename(target)
                raise
    return target


if __name__ == "__main__":
    print(export_checkpoint(Path(os.environ.get("PLAYER1_SFT_OUTPUT", DEFAULT_OUTPUT)).resolve()))
