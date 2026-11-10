"""Process orchestration for experiment runs."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.runs.artifacts import (
    evaluation_path,
    load_evaluation,
    write_run_meta,
    write_experiment_manifest,
)
from tools.runs.spec import ExperimentSpec, RunRecord, run_dir_name

MAIN_BOOL_OVERRIDE_FLAGS: dict[str, tuple[str, str]] = {
    "headless": ("--headless", "--headed"),
}
RUN_START_DELAY_S = 1.0
PROCESS_POLL_INTERVAL_S = 0.1


@dataclass(frozen=True)
class ExperimentRunContext:
    root: Path
    main_py: Path
    output_dir: Path
    run_dir: Path
    experiment_name: str
    experiment_path: Path
    run_overrides: dict[str, Any]
    base_port: int
    max_parallel: int
    wave_count: int
    total_runs: int
    run_order: list[str]
    model_endpoints: tuple[str, ...]


def build_experiment_context(
    *,
    root: Path,
    output_dir: Path,
    experiment: ExperimentSpec,
    run_overrides: dict[str, Any],
    base_port: int,
    max_parallel: int,
    model_endpoints: tuple[str, ...] = (),
) -> ExperimentRunContext:
    return ExperimentRunContext(
        root=root,
        main_py=root / "main.py",
        output_dir=output_dir,
        run_dir=output_dir / "runs",
        experiment_name=experiment.name,
        experiment_path=experiment.path,
        run_overrides=run_overrides,
        base_port=base_port,
        max_parallel=max_parallel,
        wave_count=len(experiment.repeat_waves),
        total_runs=len(experiment.runs),
        run_order=[run_dir_name(run) for run in experiment.runs],
        model_endpoints=model_endpoints,
    )


def start_experiment(context: ExperimentRunContext) -> None:
    try:
        context.output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise FileExistsError(
            f"Experiment output already exists: {context.output_dir}"
        ) from None
    write_experiment_manifest(
        context.output_dir,
        experiment_id=context.output_dir.name,
        experiment_name=context.experiment_name,
        experiment_yaml=str(context.experiment_path),
        base_port=context.base_port,
        max_parallel=context.max_parallel,
        wave_count=context.wave_count,
        total_runs=context.total_runs,
        run_order=context.run_order,
        model_endpoints=list(context.model_endpoints),
        ended_at=None,
        status="running",
    )


def resolve_bool_override(experiment: dict[str, Any], key: str) -> bool | None:
    experiment_value = experiment.get(key)
    if isinstance(experiment_value, bool):
        return bool(experiment_value)
    return None


def build_run_overrides(experiment: dict[str, Any]) -> dict[str, Any]:
    removed_keys = [
        key
        for key in ("pause_during_inference", "enable_memory", "memory_rounds")
        if key in experiment
    ]
    if removed_keys:
        joined = ", ".join(removed_keys)
        raise ValueError(
            f"Experiment overrides no longer support: {joined}. Use task/model catalog config instead."
        )

    run_overrides: dict[str, Any] = {}
    for key in ("headless",):
        value = resolve_bool_override(experiment, key)
        if value is not None:
            run_overrides[key] = value
    return run_overrides


def update_live_experiment_manifest(
    context: ExperimentRunContext,
    *,
    rows: list[dict[str, Any]],
    active_run_ids: list[str],
    final: bool = False,
) -> dict[str, Any]:
    counts = {
        "completed_runs": len(rows),
        "success_runs": sum(1 for row in rows if row.get("final_status") == "success"),
        "fail_runs": sum(1 for row in rows if row.get("final_status") == "fail"),
        "error_runs": sum(1 for row in rows if row.get("final_status") == "error"),
        "incomplete_runs": sum(
            1 for row in rows if row.get("final_status") == "incomplete"
        ),
    }
    payload = {
        "experiment_id": context.output_dir.name,
        "experiment_name": context.experiment_name,
        "experiment_yaml": str(context.experiment_path),
        "base_port": context.base_port,
        "max_parallel": context.max_parallel,
        "wave_count": context.wave_count,
        "total_runs": context.total_runs,
        "active_run_ids": active_run_ids,
        "run_order": list(context.run_order),
        "model_endpoints": list(context.model_endpoints),
        **counts,
    }
    if final:
        status = (
            "completed_with_errors"
            if counts["error_runs"] or counts["incomplete_runs"]
            else "completed"
        )
        return write_experiment_manifest(
            context.output_dir,
            **payload,
            ended_at=datetime.now().isoformat(),
            status=status,
        )
    return write_experiment_manifest(
        context.output_dir, **payload, ended_at=None, status="running"
    )


def start_run(
    run: RunRecord,
    context: ExperimentRunContext,
    *,
    model_endpoint: str | None = None,
) -> RunRecord:
    idx = int(run["run_index"])
    port = context.base_port + idx - 1
    run_meta = {
        "run_index": idx,
        "repeat_index": int(run["repeat_index"]),
        "preset": str(run["preset"]),
        "game_id": str(run["game_id"]),
        "task_id": str(run["task_id"]),
        "model_spec": str(run["model_spec"]),
        "model_endpoint": model_endpoint,
    }

    one_run_dir = context.run_dir / run_dir_name(run)
    try:
        one_run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise FileExistsError(f"Run output already exists: {one_run_dir}") from None

    cmd = [
        sys.executable,
        str(context.main_py),
        "--config",
        run_meta["preset"],
        "--port",
        str(port),
        "--log-root",
        str(one_run_dir),
    ]
    for key, value in context.run_overrides.items():
        flags = MAIN_BOOL_OVERRIDE_FLAGS.get(key)
        if flags is not None:
            cmd.append(flags[0] if value else flags[1])
    if model_endpoint:
        cmd.extend(["--model-endpoint", model_endpoint])

    stderr_log = one_run_dir / "stderr.log"
    log_handle = stderr_log.open("w", encoding="utf-8")

    write_run_meta(
        one_run_dir,
        run_id=one_run_dir.name,
        mode="experiment",
        experiment_id=context.output_dir.name,
        experiment_name=context.experiment_name,
        port=port,
        stderr_log="stderr.log",
        launcher_pid=os.getpid(),
        return_code=None,
        ended_at=None,
        status="starting",
        **run_meta,
    )
    proc = subprocess.Popen(
        cmd,
        cwd=str(context.root),
        stdout=log_handle,
        stderr=log_handle,
    )

    return {
        **run_meta,
        "proc": proc,
        "port": port,
        "run_dir": one_run_dir,
        "stderr_log": stderr_log,
        "log_handle": log_handle,
        "started_at": time.time(),
    }


def collect_run_row(
    run_record: RunRecord,
) -> dict[str, Any]:
    proc = run_record["proc"]
    rc = proc.poll()
    if rc is None:
        raise RuntimeError("collect called before process exit")

    run_record["log_handle"].close()

    evaluation = load_evaluation(run_record["run_dir"])
    eval_path_obj = evaluation_path(run_record["run_dir"])
    eval_path = str(eval_path_obj) if evaluation is not None else None
    eval_data = evaluation or {}
    task_status = eval_data.get("task_status")
    normalized_task_status = (
        task_status.strip().lower() if isinstance(task_status, str) else None
    )
    has_final_evaluation = (
        evaluation is not None
        and eval_data.get("finalized") is True
        and normalized_task_status in {"success", "fail"}
    )
    run_status = (
        "error" if rc != 0 else "completed" if has_final_evaluation else "incomplete"
    )
    write_run_meta(
        run_record["run_dir"],
        return_code=rc,
        ended_at=datetime.now().isoformat(),
        status=run_status,
    )

    use_final_evaluation = rc == 0 and has_final_evaluation
    metrics = (
        eval_data.get("metrics")
        if use_final_evaluation and isinstance(eval_data.get("metrics"), dict)
        else {}
    )
    frame_timing = (
        eval_data.get("frame_timing")
        if isinstance(eval_data.get("frame_timing"), dict)
        else {}
    )
    if rc != 0:
        final_status = "error"
    elif not has_final_evaluation:
        final_status = "incomplete"
    else:
        final_status = normalized_task_status

    run_fields = {
        key: run_record[key]
        for key in (
            "preset",
            "game_id",
            "task_id",
            "model_spec",
            "model_endpoint",
            "repeat_index",
            "port",
        )
    }
    row = {
        "run_index": int(run_record["run_index"]),
        **run_fields,
        "duration_sec": round(time.time() - float(run_record["started_at"]), 3),
        "final_status": final_status,
        "final_score": metrics.get("score"),
        "progress": eval_data.get("progress") if use_final_evaluation else None,
        "step": eval_data.get("step"),
        "max_steps": eval_data.get("max_steps"),
        "benchmark_release": eval_data.get("benchmark_release"),
        "browser_gameplay_time_ms": frame_timing.get("browser_gameplay_time_ms"),
        "controlled_gameplay_time_ms": frame_timing.get(
            "cumulative_controlled_gameplay_time_ms"
        ),
        "should_stop": eval_data.get("should_stop") if use_final_evaluation else None,
        "eval_path": eval_path,
        "run_dir": str(run_record["run_dir"]),
        "stderr_log": str(run_record["stderr_log"]),
    }

    return row


def run_wave(
    wave_runs: list[RunRecord],
    *,
    context: ExperimentRunContext,
    wave_idx: int,
    completed_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    wave_parallel = max(1, min(context.max_parallel, len(wave_runs)))
    print(
        f"\n[WAVE {wave_idx}/{context.wave_count}] runs={len(wave_runs)} parallel={wave_parallel}"
    )

    active_runs: dict[int, RunRecord] = {}
    next_run_idx = 0
    new_rows: list[dict[str, Any]] = []

    def update_manifest() -> None:
        update_live_experiment_manifest(
            context,
            rows=completed_rows + new_rows,
            active_run_ids=[item["run_dir"].name for item in active_runs.values()],
        )

    while next_run_idx < len(wave_runs) or active_runs:
        while next_run_idx < len(wave_runs) and len(active_runs) < wave_parallel:
            run = wave_runs[next_run_idx]
            model_endpoint = None
            if context.model_endpoints:
                endpoint_index = (int(run["run_index"]) - 1) % len(
                    context.model_endpoints
                )
                model_endpoint = context.model_endpoints[endpoint_index]
            run_record = start_run(
                run,
                context,
                model_endpoint=model_endpoint,
            )
            active_runs[int(run_record["run_index"])] = run_record
            next_run_idx += 1

            update_manifest()
            print(
                f"[RUN {run_record['run_index']}/{context.total_runs}] started "
                f"{run_record['run_dir'].name}"
            )
            time.sleep(RUN_START_DELAY_S)

        if not active_runs:
            continue

        for run_index, run_record in list(active_runs.items()):
            if run_record["proc"].poll() is None:
                continue
            row = collect_run_row(run_record)
            new_rows.append(row)
            print(
                f"[RUN {row['run_index']}/{context.total_runs}] "
                f"{row['final_status']} in {row['duration_sec']:.3f}s"
            )
            active_runs.pop(run_index, None)
            update_manifest()

        if active_runs:
            time.sleep(PROCESS_POLL_INTERVAL_S)

    print(
        f"[WAVE {wave_idx}/{context.wave_count}] completed "
        f"({len(completed_rows) + len(new_rows)}/{context.total_runs} runs finished)."
    )
    return new_rows
