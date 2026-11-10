"""Prepare recordings, annotate fixed actions, and publish a Player-1 dataset."""

from __future__ import annotations

import json
import math
from pathlib import Path

from filelock import FileLock, Timeout

from player1_data.annotate.client import Client, image
from player1_data.annotate.game import annotate_game
from player1_data.annotate.reasoning import annotate_reasoning
from player1_data.annotate.task import annotate_task
from player1_data.files import fingerprint
from player1_data.sources.recording import ADAPTER_IDS, open_recording
from player1_data.standardize.trajectory import prepare_recording
from player1_data.write import write_dataset


def load_config(path: Path):
    path = Path(path).resolve(strict=True)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) - {"recordings", "split_seed", "validation_basis_points"}:
        raise ValueError("Config permits only recordings, split_seed and validation_basis_points")
    if not isinstance(value.get("recordings"), list) or not value["recordings"]:
        raise ValueError("Config needs an explicit nonempty recordings list")
    allowed = {
        "source",
        "input",
        "video",
        "game",
        "mode",
        "count",
        "start_ms",
        "calibration",
        "filter",
        "regions_ns",
        "excluded_ns",
        "source_revision",
        "source_root",
        "session_allowlist",
    }
    for record in value["recordings"]:
        if not isinstance(record, dict) or not {"source", "input", "game"} <= record.keys() or record.keys() - allowed:
            raise ValueError("Recording has missing or unknown fields")
        game = record["game"]
        if (
            not isinstance(game, dict)
            or set(game) != {"name", "version"}
            or any(not isinstance(v, str) or not v.strip() for v in game.values())
        ):
            raise ValueError("Every recording needs an explicit game name and version")
        if record["source"] not in ADAPTER_IDS or record.get("mode", "gameplay") not in {"gameplay", "gui"}:
            raise ValueError("Unknown recording source or mode")
        if type(record.get("count", 1)) is not int or record.get("count", 1) < 1:
            raise ValueError("Recording count must be a positive integer")
        start = record.get("start_ms", 2000)
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0:
            raise ValueError("Recording start_ms must be nonnegative")
        for key in ("input", "video", "source_root", "session_allowlist"):
            if record.get(key):
                record[key] = str((path.parent / record[key]).resolve(strict=True))
        if record["source"] == "d2e" and not {"source_root", "session_allowlist"} <= record.keys():
            raise ValueError("D2E requires an explicit source_root and reviewed session_allowlist")
    return value


def run(config: dict, *, work: Path, output: Path, client: Client | None = None):
    """Reuse matching completed work and write a new immutable dataset snapshot."""
    work, output = Path(work).resolve(), Path(output).absolute()
    if output.is_symlink():
        raise ValueError("Dataset output must not be a symbolic link")
    output = output.resolve()
    if work == output or work.is_relative_to(output) or output.is_relative_to(work):
        raise ValueError("Work and dataset output directories must be disjoint")
    if output.exists() or output.is_symlink():
        raise ValueError("Dataset output already exists; choose a new version directory")
    for record in config["recordings"]:
        source = Path(record["input"]).resolve(strict=True)
        raw = source if source.is_dir() else source.parent
        for target in (work, output):
            if target == raw or target.is_relative_to(raw) or raw.is_relative_to(target):
                raise ValueError("Raw inputs and write targets must be disjoint")
    client = client or Client.from_environment()
    work.mkdir(parents=True, exist_ok=True)
    lock = FileLock(work / ".writer.lock", timeout=0)
    try:
        lock.acquire()
    except Timeout:
        raise ValueError("Work directory is already locked by a producer") from None
    try:
        prepared, seen, spans = [], set(), {}
        for record in config["recordings"]:
            adapter = open_recording(record)
            for root, trajectory in prepare_recording(adapter, record, work):
                identity = trajectory["identity"]
                key = tuple(sorted(identity.items()))
                if key in seen:
                    raise ValueError("Config repeats a source trajectory")
                seen.add(key)
                session = (identity["adapter_id"], identity["dataset_id"], identity["session_id"])
                start, end = trajectory["source_span_ns"]
                if any(start < b and end > a for a, b in spans.get(session, [])):
                    raise ValueError("Config selects overlapping intervals from one physical recording")
                spans.setdefault(session, []).append((start, end))
                prepared.append((root, trajectory))
        games = {}
        for _, trajectory in prepared:
            games.setdefault(fingerprint(trajectory["game"]), []).append(trajectory)
        profiles = {key: annotate_game(items[0]["game"], items, client, work / "games") for key, items in games.items()}

        def annotated():
            for root, trajectory in prepared:
                profile = profiles[fingerprint(trajectory["game"])]
                images = {turn["image"]: image(root / turn["image"]) for turn in trajectory["turns"]}
                task = annotate_task(trajectory, profile, root, client, images)
                reasoning = annotate_reasoning(trajectory, profile, task, root, client, images)
                yield {
                    "root": root,
                    "trajectory": trajectory,
                    "profile": profile,
                    "task": task,
                    "reasoning": reasoning,
                    "provider": client.identity(),
                }

        return write_dataset(
            annotated(),
            output,
            split_seed=config.get("split_seed", "player1-data"),
            validation_basis_points=config.get("validation_basis_points", 0),
        )
    finally:
        lock.release()
