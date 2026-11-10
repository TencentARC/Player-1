"""Canonical run artifacts, metadata validation, and JSON file access."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_META_FILENAME = "run_meta.json"
EXPERIMENT_MANIFEST_FILENAME = "experiment_manifest.json"
EVALUATION_FILENAME = "evaluation.json"
INTERACTIONS_FILENAME = "interactions.jsonl"
RUN_MODES = {"standalone", "experiment"}


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one JSON object and report the source path on invalid data."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def write_json_object(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace a JSON object file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def append_jsonl_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")


def _parse_jsonl_line(raw: bytes, path: Path, line_number: int) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSONL record at {path}:{line_number}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object at {path}:{line_number}")
    return payload


def read_jsonl_objects(
    path: Path,
    *,
    allow_incomplete_tail: bool = False,
) -> list[dict[str, Any]]:
    """Read JSONL objects, optionally ignoring only an unfinished final line."""
    raw = path.read_bytes()
    lines = raw.splitlines()
    tail_is_open = bool(raw) and not raw.endswith((b"\n", b"\r"))
    records: list[dict[str, Any]] = []

    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(_parse_jsonl_line(line, path, index))
        except ValueError:
            if allow_incomplete_tail and tail_is_open and index == len(lines):
                break
            raise
    return records


def read_last_jsonl_object(
    path: Path,
    *,
    allow_incomplete_tail: bool = False,
) -> dict[str, Any] | None:
    """Read the last complete JSONL object without scanning the whole file."""
    if not path.is_file():
        return None

    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        if position == 0:
            return None

        raw = b""
        while position > 0 and raw.count(b"\n") < 2:
            chunk_size = min(64 * 1024, position)
            position -= chunk_size
            handle.seek(position)
            raw = handle.read(chunk_size) + raw

    lines = raw.split(b"\n")
    tail_index = len(lines) - 1
    tail_is_open = not raw.endswith(b"\n")

    for index in range(tail_index, -1, -1):
        line = lines[index].strip()
        if not line:
            continue
        try:
            return _parse_jsonl_line(line, path, index + 1)
        except ValueError:
            if allow_incomplete_tail and tail_is_open and index == tail_index:
                continue
            raise
    return None


def default_results_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "results"


def run_meta_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / RUN_META_FILENAME


def experiment_manifest_path(experiment_dir: str | Path) -> Path:
    return Path(experiment_dir) / EXPERIMENT_MANIFEST_FILENAME


def evaluation_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "agent_0" / "evaluation" / EVALUATION_FILENAME


def _validate_local_file(path: Path, root: Path) -> None:
    if (
        root.is_symlink()
        or path.is_symlink()
        or (path.exists() and not path.resolve().is_relative_to(root.resolve()))
    ):
        raise ValueError(f"Artifact escapes its canonical directory: {path}")


def load_evaluation(run_dir: str | Path) -> dict[str, Any] | None:
    run_dir = Path(run_dir)
    path = evaluation_path(run_dir)
    _validate_local_file(path, run_dir)
    if not path.is_file():
        return None
    return read_json_object(path)


def _require_text(payload: dict[str, Any], field: str, path: Path) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path.name} must define non-empty {field}: {path}")
    return value.strip()


def _validate_run_meta(run_dir: Path, payload: dict[str, Any]) -> None:
    path = run_meta_path(run_dir)
    run_id = _require_text(payload, "run_id", path)
    mode = _require_text(payload, "mode", path)
    if mode not in RUN_MODES:
        raise ValueError(f"Invalid run mode {mode!r}: {path}")
    if run_id != run_dir.name:
        raise ValueError(f"run_id must match directory {run_dir.name!r}: {path}")

    if mode == "standalone":
        if run_dir.parent.name == "runs":
            raise ValueError(f"Standalone run cannot live under runs/: {path}")
        return

    experiment_id = _require_text(payload, "experiment_id", path)
    _require_text(payload, "experiment_name", path)
    if run_dir.parent.name != "runs":
        raise ValueError(f"Experiment run must live under <experiment>/runs/: {path}")
    if experiment_id != run_dir.parent.parent.name:
        raise ValueError(
            f"experiment_id must match directory {run_dir.parent.parent.name!r}: {path}"
        )


def _validate_experiment_manifest(
    experiment_dir: Path,
    payload: dict[str, Any],
) -> None:
    path = experiment_manifest_path(experiment_dir)
    experiment_id = _require_text(payload, "experiment_id", path)
    _require_text(payload, "experiment_name", path)
    if experiment_id != experiment_dir.name:
        raise ValueError(
            f"experiment_id must match directory {experiment_dir.name!r}: {path}"
        )


def read_run_meta(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    path = run_meta_path(run_dir)
    _validate_local_file(path, run_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Missing {RUN_META_FILENAME}: {path}")
    payload = read_json_object(path)
    _validate_run_meta(run_dir, payload)
    return payload


def read_experiment_manifest(experiment_dir: str | Path) -> dict[str, Any]:
    experiment_dir = Path(experiment_dir)
    path = experiment_manifest_path(experiment_dir)
    _validate_local_file(path, experiment_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Missing {EXPERIMENT_MANIFEST_FILENAME}: {path}")
    payload = read_json_object(path)
    _validate_experiment_manifest(experiment_dir, payload)
    return payload


def _updated_payload(path: Path, fields: dict[str, Any]) -> dict[str, Any]:
    payload = read_json_object(path) if path.is_file() else {}
    payload.update(fields)
    now = datetime.now().isoformat()
    payload["started_at"] = payload.get("started_at") or now
    payload["updated_at"] = fields.get("updated_at") or now
    return payload


def write_run_meta(run_dir: str | Path, **fields: Any) -> dict[str, Any]:
    run_dir = Path(run_dir)
    path = run_meta_path(run_dir)
    _validate_local_file(path, run_dir)
    payload = _updated_payload(path, fields)
    _validate_run_meta(run_dir, payload)
    write_json_object(path, payload)
    return payload


def write_experiment_manifest(
    experiment_dir: str | Path,
    **fields: Any,
) -> dict[str, Any]:
    experiment_dir = Path(experiment_dir)
    path = experiment_manifest_path(experiment_dir)
    _validate_local_file(path, experiment_dir)
    payload = _updated_payload(path, fields)
    _validate_experiment_manifest(experiment_dir, payload)
    write_json_object(path, payload)
    return payload


def _marked_directories(root: Path, marker: str) -> list[Path]:
    root = root.resolve()
    if not root.is_dir():
        return []
    directories = []
    for path in root.iterdir():
        marker_path = path / marker
        if (
            path.is_dir()
            and not path.is_symlink()
            and marker_path.is_file()
            and not marker_path.is_symlink()
            and marker_path.resolve().is_relative_to(path.resolve())
        ):
            directories.append(path)
    return sorted(directories, key=lambda path: path.stat().st_mtime, reverse=True)


def list_experiment_dirs(results_dir: str | Path) -> list[Path]:
    return _marked_directories(Path(results_dir), EXPERIMENT_MANIFEST_FILENAME)


def list_experiment_run_dirs(experiment_dir: str | Path) -> list[Path]:
    runs_dir = Path(experiment_dir).resolve() / "runs"
    if runs_dir.is_symlink():
        return []
    return _marked_directories(runs_dir, RUN_META_FILENAME)


def list_standalone_run_dirs(results_dir: str | Path) -> list[Path]:
    return _marked_directories(Path(results_dir), RUN_META_FILENAME)


def list_all_run_dirs(results_dir: str | Path) -> list[Path]:
    results_dir = Path(results_dir)
    run_dirs = list_standalone_run_dirs(results_dir)
    for experiment_dir in list_experiment_dirs(results_dir):
        run_dirs.extend(list_experiment_run_dirs(experiment_dir))
    return run_dirs


def list_interaction_paths(run_dir: str | Path) -> list[Path]:
    """List canonical interaction streams without following symlinks."""
    run_dir = Path(run_dir).resolve()
    return sorted(
        path
        for path in run_dir.glob("agent_*/interactions.jsonl")
        if path.is_file()
        and not path.is_symlink()
        and not path.parent.is_symlink()
        and path.resolve().is_relative_to(run_dir)
    )


def _resolve_child(root: Path, *parts: str) -> Path:
    root = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Path escapes results directory: {'/'.join(parts)}")
    return candidate


def resolve_experiment_dir(results_dir: str | Path, experiment_id: str) -> Path:
    candidate = _resolve_child(Path(results_dir), experiment_id)
    if not experiment_manifest_path(candidate).is_file():
        raise FileNotFoundError(f"Unknown experiment id: {experiment_id}")
    read_experiment_manifest(candidate)
    return candidate


def resolve_run_dir(
    results_dir: str | Path,
    run_id: str,
    *,
    experiment_id: str | None = None,
) -> Path:
    if experiment_id is None:
        candidate = _resolve_child(Path(results_dir), run_id)
        expected_mode = "standalone"
        description = run_id
    else:
        experiment_dir = resolve_experiment_dir(results_dir, experiment_id)
        candidate = _resolve_child(experiment_dir, "runs", run_id)
        expected_mode = "experiment"
        description = f"{experiment_id}/{run_id}"

    if not run_meta_path(candidate).is_file():
        raise FileNotFoundError(f"Unknown run id: {description}")
    metadata = read_run_meta(candidate)
    if metadata["mode"] != expected_mode:
        raise ValueError(f"Run {description} is not {expected_mode}")
    return candidate


def _artifact_path(
    agent_dir: Path,
    path_base: Path,
    value: str | None,
) -> str | None:
    if not value:
        return None
    base = path_base.resolve()
    candidate = (agent_dir / value).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"Interaction artifact escapes results root: {value}")
    return Path(os.path.relpath(candidate, base)).as_posix()


def _require_agent_id(payload: dict[str, Any], path: Path) -> str:
    agent_id = payload.get("agent_id")
    if isinstance(agent_id, str) and agent_id.strip():
        return agent_id.strip()
    raise ValueError(f"Interaction must define non-empty agent_id: {path}")


def load_interactions(
    agent_dir: str | Path,
    path_base: str | Path,
    *,
    allow_incomplete_tail: bool = False,
) -> list[dict[str, Any]]:
    """Load one agent's interaction stream for monitor and export consumers."""
    agent_dir = Path(agent_dir)
    path_base = Path(path_base)
    path = agent_dir / INTERACTIONS_FILENAME
    if not path.is_file():
        return []
    records = read_jsonl_objects(
        path,
        allow_incomplete_tail=allow_incomplete_tail,
    )
    interactions: list[dict[str, Any]] = []

    for payload in records:
        input_section = payload["input"]
        output_section = payload["output"]
        interaction_id = int(payload["interaction_id"])
        memory_screenshots = [
            artifact
            for value in input_section.get("memory_screenshots", [])
            if (artifact := _artifact_path(agent_dir, path_base, value)) is not None
        ]
        interactions.append(
            {
                "agent_id": _require_agent_id(payload, path),
                "interaction_id": interaction_id,
                "timestamp": payload["timestamp"],
                "prompt": input_section.get("prompt", ""),
                "raw_message_sent": input_section.get("raw_message_sent", ""),
                "raw_response": output_section.get("raw_response", ""),
                "parsed_action": output_section.get("parsed_action"),
                "executed_action": output_section.get("executed_action"),
                "screenshot": _artifact_path(
                    agent_dir,
                    path_base,
                    input_section.get("screenshot"),
                ),
                "memory_context": input_section.get("memory_context"),
                "memory_screenshots": memory_screenshots,
                "error": output_section.get("error"),
                "game_state": payload.get("game_state"),
                "task_evaluation": payload.get("task_evaluation"),
            }
        )
    return interactions


def build_interaction_payload(
    run_dir: str | Path,
    logs_root: str | Path,
    *,
    allow_incomplete_tail: bool = False,
) -> dict[str, Any]:
    """Merge canonical interaction streams from every agent in one run."""
    run_dir = Path(run_dir).resolve()
    logs_root = Path(logs_root).resolve()
    if not run_dir.is_relative_to(logs_root):
        raise ValueError(f"Run directory escapes logs root: {run_dir}")
    agent_dirs = [path.parent for path in list_interaction_paths(run_dir)]

    interactions: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    for agent_dir in agent_dirs:
        entries = load_interactions(
            agent_dir,
            logs_root,
            allow_incomplete_tail=allow_incomplete_tail,
        )
        if not entries:
            continue
        agent_id = entries[0]["agent_id"]
        if any(entry["agent_id"] != agent_id for entry in entries):
            raise ValueError(
                f"Interactions must use one agent_id per file: {agent_dir}"
            )
        interactions.extend(entries)
        agents.append({"agent_id": agent_id})

    interactions.sort(
        key=lambda item: (item["timestamp"], item["interaction_id"], item["agent_id"])
    )
    return {
        "agents": agents,
        "interactions": interactions,
    }
