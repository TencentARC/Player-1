"""Run directory and metadata lifecycle helpers."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tools.runs.artifacts import default_results_dir

if TYPE_CHECKING:
    from runtime.runtime_config import RuntimeConfig


def _default_run_dir(runtime_config: RuntimeConfig) -> Path:
    model_spec = (
        runtime_config.model_ids[0]
        if len(runtime_config.model_ids) == 1
        else "-".join(runtime_config.model_ids)
    )
    run_name = (
        f"run_{runtime_config.log_session_id}_"
        f"{runtime_config.game_id}_{runtime_config.task_id}_{model_spec}"
    )
    return default_results_dir() / run_name


def prepare_run_artifacts(
    runtime_config: RuntimeConfig,
    *,
    config_preset: str,
    port: int | None,
    log_root: str | None = None,
) -> None:
    """Create the run directory and initialize its live metadata."""
    if log_root is not None:
        runtime_config.log_root = log_root

    run_dir = (
        Path(runtime_config.log_root)
        if runtime_config.log_root
        else _default_run_dir(runtime_config)
    )
    if run_dir.is_symlink():
        raise FileExistsError(f"Run output cannot be a symlink: {run_dir}")
    from tools.runs.artifacts import read_run_meta, run_meta_path, write_run_meta

    meta_fields = dict(
        run_id=run_dir.name,
        preset=config_preset,
        game_id=runtime_config.game_id,
        task_id=runtime_config.task_id,
        model_spec=",".join(runtime_config.model_ids),
        benchmark_release=runtime_config.benchmark_release,
        max_steps=runtime_config.max_steps,
        port=port,
        session_id=runtime_config.log_session_id,
        return_code=None,
        ended_at=None,
        status="running",
    )
    metadata_path = run_meta_path(run_dir)
    if metadata_path.is_file():
        existing = read_run_meta(run_dir)
        if existing.get("mode") != "experiment" or existing.get("status") != "starting":
            raise FileExistsError(f"Run output already exists: {run_dir}")
        if existing.get("launcher_pid") != os.getppid():
            raise FileExistsError(
                f"Prepared experiment run is not owned by this launcher: {run_dir}"
            )
        for field in ("preset", "game_id", "task_id", "model_spec", "port"):
            if existing.get(field) != meta_fields[field]:
                raise ValueError(
                    f"Prepared experiment run has mismatched {field}: {run_dir}"
                )
        meta_fields["launcher_pid"] = None
    else:
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise FileExistsError(f"Run output already exists: {run_dir}") from None
        meta_fields["mode"] = "standalone"

    runtime_config.log_root = str(run_dir)
    write_run_meta(run_dir, **meta_fields)


def finalize_run_metadata(
    runtime_config: RuntimeConfig,
    *,
    return_code: int | None,
    status: str,
) -> None:
    """Persist the terminal status for a prepared run."""
    if not runtime_config.log_root:
        return

    from tools.runs.artifacts import write_run_meta

    write_run_meta(
        runtime_config.log_root,
        return_code=return_code,
        status=status,
        ended_at=datetime.now().isoformat(),
    )
