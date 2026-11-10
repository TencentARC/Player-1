"""Experiment report writers."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.runs.artifacts import write_json_object

RUN_FIELDS = [
    "run_index",
    "preset",
    "game_id",
    "task_id",
    "model_spec",
    "model_endpoint",
    "repeat_index",
    "port",
    "duration_sec",
    "final_status",
    "final_score",
    "progress",
    "step",
    "max_steps",
    "benchmark_release",
    "browser_gameplay_time_ms",
    "controlled_gameplay_time_ms",
    "should_stop",
    "eval_path",
    "run_dir",
    "stderr_log",
]
AGGREGATE_FIELDS = [
    "model_spec",
    "total_runs",
    "success_runs",
    "fail_runs",
    "error_runs",
    "incomplete_runs",
    "task_avg_success_rate",
    "task_avg_dur_sec",
    "task_avg_progress",
]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    success = sum(1 for row in rows if row.get("final_status") == "success")
    fail = sum(1 for row in rows if row.get("final_status") == "fail")
    error = sum(1 for row in rows if row.get("final_status") == "error")
    incomplete = sum(1 for row in rows if row.get("final_status") == "incomplete")
    finalized_task_runs = success + fail
    durations = [
        float(row["duration_sec"])
        for row in rows
        if isinstance(row.get("duration_sec"), int | float)
    ]
    progress_values = [
        float(row["progress"])
        for row in rows
        if isinstance(row.get("progress"), int | float)
    ]
    return {
        "total_runs": total,
        "success_runs": success,
        "fail_runs": fail,
        "error_runs": error,
        "incomplete_runs": incomplete,
        "task_avg_success_rate": (
            success / finalized_task_runs if finalized_task_runs else 0.0
        ),
        "task_avg_progress": (sum(progress_values) / len(progress_values))
        if progress_values
        else None,
        "task_avg_dur_sec": (sum(durations) / len(durations)) if durations else None,
    }


def report_model_spec(model_spec: str) -> str:
    parts = [part.strip() for part in str(model_spec).split(",") if part.strip()]
    if not parts:
        return str(model_spec).strip()
    if all(part == parts[0] for part in parts):
        return parts[0]
    return ",".join(parts)


def aggregate_by_model(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[report_model_spec(str(row["model_spec"]))].append(row)

    by_model: list[dict[str, Any]] = []
    for model_spec, model_rows in sorted(grouped.items()):
        model_summary = summary(model_rows)
        model_summary["model_spec"] = model_spec
        by_model.append(model_summary)
    return by_model


def write_experiment_outputs(
    output_dir: Path,
    experiment_name: str,
    experiment_path: Path,
    started_at: str,
    rows: list[dict[str, Any]],
) -> None:
    by_model = aggregate_by_model(rows)
    experiment_summary = {
        "experiment_name": experiment_name,
        "experiment_yaml": str(experiment_path),
        "started_at": started_at,
        "ended_at": datetime.now().isoformat(),
        "run_count": len(rows),
        "overall": summary(rows),
        "by_model": by_model,
    }
    write_json_object(output_dir / "summary.json", experiment_summary)
    write_csv(output_dir / "runs.csv", rows, RUN_FIELDS)
    write_csv(output_dir / "aggregate_by_model.csv", by_model, AGGREGATE_FIELDS)
